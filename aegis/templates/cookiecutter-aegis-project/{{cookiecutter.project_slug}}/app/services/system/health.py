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
        SystemStatus with all component health information organized as Aegis tree
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
            "System container metrics"
            if backend_healthy
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

    # Create Aegis root structure with components underneath
    aegis_healthy = all(status.healthy for status in all_statuses)
    aegis_message = (
        "Aegis Stack application" if aegis_healthy else "Aegis Stack has issues"
    )

    root_components = {
        "aegis": ComponentStatus(
            name="aegis",
            healthy=aegis_healthy,
            message=aegis_message,
            response_time_ms=None,
            metadata={"type": "application_root", "version": "1.0"},
            sub_components=component_results,
        )
    }

    # Get system information
    system_info = _get_system_info()

    status = SystemStatus(
        components=root_components,
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


async def check_cache_health() -> ComponentStatus:
    """
    Check cache connectivity and basic functionality.

    Returns:
        ComponentStatus indicating cache health
    """
    try:
        import redis.asyncio as aioredis

        # Create Redis connection with timeout
        redis_client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.REDIS_URL,
            db=settings.REDIS_DB,
            socket_timeout=settings.HEALTH_CHECK_TIMEOUT_SECONDS,
            socket_connect_timeout=settings.HEALTH_CHECK_TIMEOUT_SECONDS,
        )

        start_time = datetime.now(UTC)

        # Test basic connectivity with ping
        await redis_client.ping()

        # Test basic set/get functionality
        test_key = "health_check:test"
        test_value = f"test_{start_time.timestamp()}"
        await redis_client.set(test_key, test_value, ex=10)  # Expire in 10 seconds
        retrieved_value = await redis_client.get(test_key)

        # Cleanup test key
        await redis_client.delete(test_key)
        await redis_client.close()

        # Verify test worked
        if retrieved_value.decode() != test_value:
            raise Exception("Redis set/get test failed")

        # Get Redis info for metadata
        redis_info_client: aioredis.Redis = aioredis.from_url(
            settings.REDIS_URL, db=settings.REDIS_DB
        )  # type: ignore[no-untyped-call,import-not-found]
        info = await redis_info_client.info()
        await redis_info_client.close()

        return ComponentStatus(
            name="cache",
            healthy=True,
            message="Redis cache connection and operations successful",
            response_time_ms=None,  # Will be set by caller
            metadata={
                "implementation": "redis",
                "version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "uptime_in_seconds": info.get("uptime_in_seconds", 0),
                "url": settings.REDIS_URL,
                "db": settings.REDIS_DB,
            },
        )

    except ImportError:
        return ComponentStatus(
            name="cache",
            healthy=False,
            message="Cache library not installed",
            response_time_ms=None,
            metadata={
                "implementation": "redis",
                "error": "Redis library not available",
            },
        )
    except Exception as e:
        return ComponentStatus(
            name="cache",
            healthy=False,
            message=f"Cache health check failed: {str(e)}",
            response_time_ms=None,
            metadata={
                "implementation": "redis",
                "url": settings.REDIS_URL,
                "db": settings.REDIS_DB,
                "error": str(e),
            },
        )


async def check_worker_health() -> ComponentStatus:
    """
    Check arq worker status using arq's native health checks and queue configuration.

    Returns:
        ComponentStatus indicating worker infrastructure health with queue
        sub-components
    """
    try:
        import re

        import redis.asyncio as aioredis

        # Create Redis connection
        redis_client: aioredis.Redis = aioredis.from_url(
            settings.REDIS_URL, db=settings.REDIS_DB
        )  # type: ignore[no-untyped-call,import-not-found]

        # Get functional queue configuration from settings
        functional_queues = {}
        for queue_type, queue_config in settings.WORKER_QUEUES.items():
            functional_queues[queue_type] = {
                "queue_name": queue_config["queue_name"],
                "description": queue_config["description"],
                "max_jobs": queue_config["max_jobs"],
                "timeout": queue_config["timeout_seconds"],
            }

        # Check each queue and create sub-components
        queue_sub_components = {}
        total_queued = 0
        total_completed = 0
        total_failed = 0
        total_retried = 0
        total_ongoing = 0
        overall_healthy = True
        active_workers = 0

        for queue_type, queue_config in functional_queues.items():
            queue_name = queue_config["queue_name"]

            try:
                # Get queue length (actual queued jobs)
                queue_length_result = redis_client.llen(queue_name)
                if hasattr(queue_length_result, '__await__'):
                    queue_length = await queue_length_result
                else:
                    queue_length = queue_length_result
                total_queued += queue_length

                # Look for arq health check key for this queue
                # arq health check key format: {queue_name}:health-check
                health_check_key = f"{queue_name}:health-check"
                health_check_data = await redis_client.get(health_check_key)

                # Parse arq health check data if available
                j_complete = j_failed = j_retried = j_ongoing = 0
                worker_alive = False
                last_health_check = None

                if health_check_data:
                    health_string = health_check_data.decode()
                    # Parse format: "Mar-01 17:41:22 j_complete=0 j_failed=0 ..."
                    logger.debug(
                        f"Raw health check data for {queue_type}: {health_string}"
                    )

                    # Extract timestamp (first part before job stats)
                    timestamp_match = re.match(r"^(\w+-\d+ \d+:\d+:\d+)", health_string)
                    if timestamp_match:
                        last_health_check = timestamp_match.group(1)

                    # Extract job statistics using regex
                    j_complete_match = re.search(r"j_complete=(\d+)", health_string)
                    j_failed_match = re.search(r"j_failed=(\d+)", health_string)
                    j_retried_match = re.search(r"j_retried=(\d+)", health_string)
                    j_ongoing_match = re.search(r"j_ongoing=(\d+)", health_string)

                    if j_complete_match:
                        j_complete = int(j_complete_match.group(1))
                        total_completed += j_complete
                    if j_failed_match:
                        j_failed = int(j_failed_match.group(1))
                        total_failed += j_failed
                    if j_retried_match:
                        j_retried = int(j_retried_match.group(1))
                        total_retried += j_retried
                    if j_ongoing_match:
                        j_ongoing = int(j_ongoing_match.group(1))
                        total_ongoing += j_ongoing

                    worker_alive = True
                    active_workers += 1

                # Create queue status message
                status_parts = []
                if not worker_alive:
                    status_parts.append("worker offline")
                elif j_ongoing > 0:
                    status_parts.append(f"{j_ongoing} processing")
                elif queue_length > 0:
                    status_parts.append(f"{queue_length} queued")
                else:
                    status_parts.append("idle")

                # Add job statistics to status if worker is alive
                if worker_alive and (j_complete > 0 or j_failed > 0):
                    if j_failed > 0:
                        failure_rate = (j_failed / max(j_complete + j_failed, 1)) * 100
                        status_parts.append(f"{j_failed} failed ({failure_rate:.1f}%)")
                    if j_complete > 0:
                        status_parts.append(f"{j_complete} completed")

                queue_message = (
                    f"{queue_config['description']}: {', '.join(status_parts)}"
                )

                # Queue is healthy if worker is alive and failure rate is acceptable
                failure_rate = (
                    (j_failed / max(j_complete + j_failed, 1)) * 100
                    if worker_alive
                    else 100
                )
                queue_healthy = (
                    worker_alive and failure_rate < 25
                )  # 25% failure rate threshold

                if not queue_healthy:
                    overall_healthy = False

                queue_metadata = {
                    "queue_type": queue_type,
                    "queue_name": queue_name,
                    "queued_jobs": queue_length,
                    "max_concurrency": queue_config["max_jobs"],
                    "timeout_seconds": queue_config["timeout"],
                    "description": queue_config["description"],
                    "worker_alive": worker_alive,
                    "health_check_key": health_check_key,
                }

                # Add arq health check statistics if available
                if worker_alive:
                    queue_metadata.update(
                        {
                            "jobs_completed": j_complete,
                            "jobs_failed": j_failed,
                            "jobs_retried": j_retried,
                            "jobs_ongoing": j_ongoing,
                            "failure_rate_percent": round(failure_rate, 1),
                            "last_health_check": last_health_check,
                        }
                    )
                else:
                    queue_metadata["offline_reason"] = "Health check key not found"

                queue_sub_components[queue_type] = ComponentStatus(
                    name=queue_type,
                    healthy=queue_healthy,
                    message=queue_message,
                    response_time_ms=None,
                    metadata=queue_metadata,
                    sub_components={},
                )

            except Exception as e:
                logger.error(f"Failed to check {queue_type} queue health: {e}")
                overall_healthy = False
                queue_sub_components[queue_type] = ComponentStatus(
                    name=queue_type,
                    healthy=False,
                    message=f"Queue check failed: {str(e)}",
                    response_time_ms=None,
                    metadata={
                        "queue_type": queue_type,
                        "queue_name": queue_name,
                        "error": str(e),
                    },
                    sub_components={},
                )

        await redis_client.close()

        # Create main worker status message
        message_parts = []
        if active_workers == 0:
            message_parts.append("No active workers")
            overall_healthy = False
        else:
            message_parts.append(
                f"{active_workers}/{len(functional_queues)} workers active"
            )

        if total_queued > 0:
            message_parts.append(f"{total_queued} queued")
        if total_ongoing > 0:
            message_parts.append(f"{total_ongoing} processing")
        if total_failed > 0:
            failure_rate = (total_failed / max(total_completed + total_failed, 1)) * 100
            message_parts.append(f"{total_failed} failed ({failure_rate:.1f}%)")

        main_message = f"arq worker infrastructure: {', '.join(message_parts)}"

        # Create a "queues" intermediate component that contains all queue
        # sub-components
        queues_healthy = all(queue.healthy for queue in queue_sub_components.values())
        queues_message = f"{len(functional_queues)} functional queues configured"
        if active_workers < len(functional_queues):
            queues_message += f" ({active_workers} active)"

        queues_component = ComponentStatus(
            name="queues",
            healthy=queues_healthy,
            message=queues_message,
            response_time_ms=None,
            metadata={
                "configured_queues": len(functional_queues),
                "active_workers": active_workers,
                "queue_types": list(functional_queues.keys()),
            },
            sub_components=queue_sub_components,
        )

        return ComponentStatus(
            name="worker",
            healthy=overall_healthy,
            message=main_message,
            response_time_ms=None,
            metadata={
                "total_queued": total_queued,
                "total_completed": total_completed,
                "total_failed": total_failed,
                "total_retried": total_retried,
                "total_ongoing": total_ongoing,
                "overall_failure_rate_percent": round(
                    (total_failed / max(total_completed + total_failed, 1)) * 100, 1
                )
                if total_completed + total_failed > 0
                else 0,
                "redis_url": settings.REDIS_URL,
                "queue_configuration": {
                    queue_type: {
                        "description": config["description"],
                        "max_jobs": config["max_jobs"],
                        "timeout_seconds": config["timeout"],
                    }
                    for queue_type, config in functional_queues.items()
                },
            },
            sub_components={"queues": queues_component},
        )

    except ImportError:
        return ComponentStatus(
            name="worker",
            healthy=False,
            message="Redis library not available for worker health check",
            response_time_ms=None,
            sub_components={},
        )
    except Exception as e:
        logger.error(f"Worker health check failed: {e}")
        return ComponentStatus(
            name="worker",
            healthy=False,
            message=f"Worker health check failed: {str(e)}",
            response_time_ms=None,
            metadata={
                "error": str(e),
                "redis_url": settings.REDIS_URL,
            },
            sub_components={},
        )
