"""Reading the machine: memory, disk, CPU, and one check's result.

The metric cache and the previous-status map live here because these
are the only functions that touch them - both are mutated in place,
never rebound, so importing them elsewhere shares one object.
"""

from app.core.formatting import format_bytes
import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import os
import sys
import time
from typing import Any
import weakref
import psutil
from app.core.config import settings
from app.core.log import logger
from . import activity
from .alerts import send_critical_alert, send_health_alert
from .models import ComponentStatus, ComponentStatusType, SystemStatus


# Track previous status per component for activity events
_previous_status: dict[str, ComponentStatusType] = {}


# System metrics that shouldn't create separate activity events
# (they're sub-components of backend)
SYSTEM_METRICS = {"cpu", "memory", "disk"}


# Cache for system metrics to improve performance
_system_metrics_cache: dict[str, tuple[ComponentStatus, datetime]] = {}


async def _get_cached_system_metrics(
    current_time: datetime,
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
                status=ComponentStatusType.UNHEALTHY,
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
    """Run a single health check with timing and status change tracking."""
    start_time = datetime.now(UTC)
    try:
        result = await check_fn()
        end_time = datetime.now(UTC)
        response_time = (end_time - start_time).total_seconds() * 1000

        if isinstance(result, ComponentStatus):
            result.response_time_ms = response_time

            # Track status changes and emit activity events
            current_status = result.status
            previous_status = _previous_status.get(name)

            # Skip activity events for system metrics (sub-components of backend)
            if name not in SYSTEM_METRICS:
                # Log on FIRST check (previous is None) OR status change
                if previous_status is None or previous_status != current_status:
                    event_status = (
                        "success" if current_status == ComponentStatusType.HEALTHY
                        else "error" if current_status == ComponentStatusType.UNHEALTHY
                        else "info" if current_status == ComponentStatusType.INFO
                        else "warning"
                    )
                    display_name = name.replace("_", " ").title()
                    details = result.message if result.message else None

                    if previous_status is None:
                        # First health check - use startup message with actual status
                        activity.add_event(
                            component=name,
                            event_type="startup",
                            message=f"{display_name} initialized",
                            status=event_status,
                            details=details,
                        )
                    else:
                        # Status change
                        change_msg = (
                            f"{display_name}: "
                            f"{previous_status.value} → "
                            f"{current_status.value}"
                        )
                        activity.add_event(
                            component=name,
                            event_type="status_change",
                            message=change_msg,
                            status=event_status,
                            details=details,
                        )

            _previous_status[name] = current_status

            return result
        else:
            return ComponentStatus(
                name=name,
                status=(
                    ComponentStatusType.HEALTHY if bool(result)
                    else ComponentStatusType.UNHEALTHY
                ),
                message="OK" if result else "Failed",
                response_time_ms=response_time,
            )
    except Exception as e:
        end_time = datetime.now(UTC)
        response_time = (end_time - start_time).total_seconds() * 1000
        return ComponentStatus(
            name=name,
            status=ComponentStatusType.UNHEALTHY,
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

        # Determine status based on memory usage thresholds
        if memory_percent >= settings.MEMORY_THRESHOLD_PERCENT:
            status = ComponentStatusType.UNHEALTHY
        elif memory_percent >= settings.MEMORY_THRESHOLD_PERCENT * 0.8:
            status = ComponentStatusType.WARNING
        else:
            status = ComponentStatusType.HEALTHY

        return ComponentStatus(
            name="memory",
            status=status,
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
            status=ComponentStatusType.UNHEALTHY,
            message=f"Failed to check memory: {e}",
            response_time_ms=None,
        )


async def _check_disk_space() -> ComponentStatus:
    """Check disk space usage."""
    try:
        # Run in thread to avoid blocking
        disk = await asyncio.to_thread(psutil.disk_usage, "/")
        disk_percent = (disk.used / disk.total) * 100

        # Determine status based on disk usage thresholds
        if disk_percent >= settings.DISK_THRESHOLD_PERCENT:
            status = ComponentStatusType.UNHEALTHY
        elif disk_percent >= settings.DISK_THRESHOLD_PERCENT * 0.8:
            status = ComponentStatusType.WARNING
        else:
            status = ComponentStatusType.HEALTHY

        return ComponentStatus(
            name="disk",
            status=status,
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
            status=ComponentStatusType.UNHEALTHY,
            message=f"Failed to check disk space: {e}",
            response_time_ms=None,
        )


async def _check_cpu_usage() -> ComponentStatus:
    """Check CPU usage (instant sampling)."""
    try:
        # Get instant CPU usage (non-blocking, immediate reading)
        cpu_percent = await asyncio.to_thread(psutil.cpu_percent, None)

        # Determine status based on CPU usage thresholds
        if cpu_percent >= settings.CPU_THRESHOLD_PERCENT:
            status = ComponentStatusType.UNHEALTHY
        elif cpu_percent >= settings.CPU_THRESHOLD_PERCENT * 0.8:
            status = ComponentStatusType.WARNING
        else:
            status = ComponentStatusType.HEALTHY

        return ComponentStatus(
            name="cpu",
            status=status,
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
            status=ComponentStatusType.UNHEALTHY,
            message=f"Failed to check CPU usage: {e}",
            response_time_ms=None,
        )
