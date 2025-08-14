"""
System health monitoring functions.

Pure functions for system health checking, monitoring, and status reporting.
All functions use Pydantic models for type safety and validation.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import os
import sys
from typing import Any

import psutil

from app.core.config import settings
from app.core.log import logger

from .alerts import send_critical_alert, send_health_alert
from .models import ComponentStatus, SystemStatus

# Global registry for custom health checks
_health_checks: dict[str, Callable[[], Awaitable[ComponentStatus]]] = {}

# Cache for system metrics to improve performance
_system_metrics_cache: dict[str, tuple[ComponentStatus, datetime]] = {}


def register_health_check(
    name: str, check_fn: Callable[[], Awaitable[ComponentStatus]]
) -> None:
    """
    Register a custom health check function.

    Args:
        name: Unique name for the health check
        check_fn: Async function that returns ComponentStatus or bool
    """
    _health_checks[name] = check_fn
    logger.info(f"Registered custom health check: {name}")


async def get_system_status() -> SystemStatus:
    """
    Get comprehensive system status.

    Returns:
        SystemStatus with all component health information
    """
    logger.info("Running system health checks")
    start_time = datetime.now(UTC)

    # Run custom component checks (these are top-level components)
    component_results = {}
    component_tasks = []
    for name, check_fn in _health_checks.items():
        task = asyncio.create_task(_run_health_check(name, check_fn))
        component_tasks.append((name, task))

    # Collect component results
    for name, task in component_tasks:
        try:
            component_results[name] = await task
        except Exception as e:
            logger.error(f"Component check failed for {name}: {e}")
            component_results[name] = ComponentStatus(
                name=name,
                healthy=False,
                message=f"Health check failed: {str(e)}",
                response_time_ms=None,
            )

    # Get system metrics (with caching for performance)
    system_metrics = await _get_cached_system_metrics(start_time)

    # Group system metrics under backend component if it exists
    if "backend" in component_results:
        # Backend exists - recreate with system metrics as sub-components
        backend_component = component_results["backend"]
        component_results["backend"] = ComponentStatus(
            name=backend_component.name,
            healthy=backend_component.healthy,
            message=backend_component.message,
            response_time_ms=backend_component.response_time_ms,
            metadata=backend_component.metadata,
            sub_components=system_metrics,
        )
    else:
        # Backend doesn't exist - create a virtual backend component to hold 
        # system metrics
        backend_healthy = all(metric.healthy for metric in system_metrics.values())
        backend_message = (
            "System container metrics" if backend_healthy 
            else "System container has issues"
        )
        
        component_results["backend"] = ComponentStatus(
            name="backend",
            healthy=backend_healthy,
            message=backend_message,
            response_time_ms=None,
            metadata={"type": "system_container", "virtual": True},
            sub_components=system_metrics,
        )

    # Calculate overall health (including sub-components)
    all_statuses = list(component_results.values())
    for component in component_results.values():
        all_statuses.extend(component.sub_components.values())
    overall_healthy = all(status.healthy for status in all_statuses)

    # Get system information
    system_info = _get_system_info()

    status = SystemStatus(
        components=component_results,
        overall_healthy=overall_healthy,
        timestamp=start_time,
        system_info=system_info,
    )

    # Log unhealthy components
    if not overall_healthy:
        logger.warning(
            f"System unhealthy: {status.unhealthy_components}",
            extra={"unhealthy_components": status.unhealthy_components},
        )

    return status


async def is_system_healthy() -> bool:
    """Quick check if system is overall healthy."""
    status = await get_system_status()
    return status.overall_healthy


async def check_system_status() -> None:
    """
    Scheduled health check function for use in APScheduler jobs.

    This function gets the system status and logs any issues.
    Can be extended to send alerts to Slack, email, etc.
    """
    logger.info("🩺 Running scheduled system health check")

    try:
        status = await get_system_status()

        if status.overall_healthy:
            log_msg = (
                f"✅ System healthy: {len(status.healthy_top_level_components)}/"
                f"{status.total_components} components OK"
            )
            logger.info(log_msg)
        else:
            logger.warning(
                f"⚠️ System issues detected: "
                f"{len(status.unhealthy_components)} unhealthy components",
                extra={
                    "unhealthy_components": status.unhealthy_components,
                    "health_percentage": status.health_percentage,
                },
            )

            # Log details for each unhealthy component
            for component_name in status.unhealthy_components:
                component = status.components[component_name]
                logger.error(
                    f"❌ {component_name}: {component.message}",
                    extra={"component": component.name, "metadata": component.metadata},
                )

            # Send health alerts
            await send_health_alert(status)

    except Exception as e:
        logger.error(f"💥 System health check failed: {e}")
        # Send critical alert about monitoring failure
        await send_critical_alert(f"Health monitoring failed: {e}", str(e))


async def _get_cached_system_metrics(
    current_time: datetime
) -> dict[str, ComponentStatus]:
    """Get system metrics with caching for better performance."""
    cache_duration = settings.SYSTEM_METRICS_CACHE_SECONDS
    system_metric_checks = {
        "memory": _check_memory,
        "disk": _check_disk_space,
        "cpu": _check_cpu_usage,
    }
    
    system_metrics = {}
    tasks = []
    
    for name, check_fn in system_metric_checks.items():
        # Check if we have a valid cached result
        if name in _system_metrics_cache:
            cached_result, cached_time = _system_metrics_cache[name]
            age_seconds = (current_time - cached_time).total_seconds()
            
            if age_seconds < cache_duration:
                # Use cached result
                system_metrics[name] = cached_result
                continue
        
        # Need to run the check
        task = asyncio.create_task(
            _run_health_check_with_cache(name, check_fn, current_time)
        )
        tasks.append((name, task))
    
    # Collect results from non-cached checks
    for name, task in tasks:
        try:
            system_metrics[name] = await task
        except Exception as e:
            logger.error(f"System metric check failed for {name}: {e}")
            system_metrics[name] = ComponentStatus(
                name=name,
                healthy=False,
                message=f"Health check failed: {str(e)}",
                response_time_ms=None,
            )
    
    return system_metrics


async def _run_health_check_with_cache(
    name: str, check_fn: Callable[[], Awaitable[ComponentStatus]], timestamp: datetime
) -> ComponentStatus:
    """Run health check and cache the result."""
    result = await _run_health_check(name, check_fn)
    _system_metrics_cache[name] = (result, timestamp)
    return result


async def _run_health_check(
    name: str, check_fn: Callable[[], Awaitable[ComponentStatus]]
) -> ComponentStatus:
    """Run a single health check with timing."""
    start_time = datetime.now(UTC)
    try:
        result = await check_fn()
        end_time = datetime.now(UTC)
        response_time = (end_time - start_time).total_seconds() * 1000

        if isinstance(result, ComponentStatus):
            result.response_time_ms = response_time
            return result
        else:
            return ComponentStatus(
                name=name,
                healthy=bool(result),
                message="OK" if result else "Failed",
                response_time_ms=response_time,
            )
    except Exception as e:
        end_time = datetime.now(UTC)
        response_time = (end_time - start_time).total_seconds() * 1000
        return ComponentStatus(
            name=name,
            healthy=False,
            message=f"Error: {str(e)}",
            response_time_ms=response_time,
        )


def _get_system_info() -> dict[str, Any]:
    """Get general system information."""
    try:
        return {
            "python_version": (
                f"{sys.version_info.major}."
                f"{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            "platform": psutil.WINDOWS if psutil.WINDOWS else "unix",
            "containerized": "docker" if os.path.exists("/.dockerenv") else "false",
        }
    except Exception as e:
        logger.warning(f"Failed to get system info: {e}")
        return {"error": str(e)}


async def _check_memory() -> ComponentStatus:
    """Check system memory usage."""
    try:
        # Run in thread to avoid blocking
        memory = await asyncio.to_thread(psutil.virtual_memory)
        memory_percent = memory.percent

        # Consider unhealthy if memory usage exceeds threshold
        healthy = memory_percent < settings.MEMORY_THRESHOLD_PERCENT

        return ComponentStatus(
            name="memory",
            healthy=healthy,
            message=f"Memory usage: {memory_percent:.1f}%",
            response_time_ms=None,
            metadata={
                "percent_used": memory_percent,
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "threshold_percent": settings.MEMORY_THRESHOLD_PERCENT,
            },
        )
    except Exception as e:
        return ComponentStatus(
            name="memory",
            healthy=False,
            message=f"Failed to check memory: {e}",
            response_time_ms=None,
        )


async def _check_disk_space() -> ComponentStatus:
    """Check disk space usage."""
    try:
        # Run in thread to avoid blocking
        disk = await asyncio.to_thread(psutil.disk_usage, "/")
        disk_percent = (disk.used / disk.total) * 100

        # Consider unhealthy if disk usage exceeds threshold
        healthy = disk_percent < settings.DISK_THRESHOLD_PERCENT

        return ComponentStatus(
            name="disk",
            healthy=healthy,
            message=f"Disk usage: {disk_percent:.1f}%",
            response_time_ms=None,
            metadata={
                "percent_used": disk_percent,
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "threshold_percent": settings.DISK_THRESHOLD_PERCENT,
            },
        )
    except Exception as e:
        return ComponentStatus(
            name="disk",
            healthy=False,
            message=f"Failed to check disk space: {e}",
            response_time_ms=None,
        )


async def _check_cpu_usage() -> ComponentStatus:
    """Check CPU usage (instant sampling)."""
    try:
        # Get instant CPU usage (non-blocking, immediate reading)
        cpu_percent = await asyncio.to_thread(psutil.cpu_percent, None)

        # Consider unhealthy if CPU usage exceeds threshold
        healthy = cpu_percent < settings.CPU_THRESHOLD_PERCENT

        return ComponentStatus(
            name="cpu",
            healthy=healthy,
            message=f"CPU usage: {cpu_percent:.1f}%",
            response_time_ms=None,
            metadata={
                "percent_used": cpu_percent,
                "cpu_count": psutil.cpu_count(),
                "threshold_percent": settings.CPU_THRESHOLD_PERCENT,
            },
        )
    except Exception as e:
        return ComponentStatus(
            name="cpu",
            healthy=False,
            message=f"Failed to check CPU usage: {e}",
            response_time_ms=None,
        )
