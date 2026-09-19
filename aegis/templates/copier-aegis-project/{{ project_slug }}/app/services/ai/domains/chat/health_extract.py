"""Pulling one component's line out of a system status.

Each reads ``status`` and returns the text (or numbers) the health
context puts in front of the model. No state, one component each.
"""

from typing import Any

from app.services.system.models import SystemStatus


def extract_system_resources(status: SystemStatus) -> dict[str, float]:
    """Extract CPU, memory, disk percentages from health status."""
    resources: dict[str, float] = {}

    # Navigate to backend component which contains system metrics
    aegis = status.components.get("aegis")
    if not aegis:
        return resources

    components = aegis.sub_components.get("components")
    if not components:
        return resources

    backend = components.sub_components.get("backend")
    if not backend:
        return resources

    # Extract from sub_components (cpu, memory, disk)
    for metric_name in ["cpu", "memory", "disk"]:
        metric = backend.sub_components.get(metric_name)
        if metric and metric.metadata:
            percent = metric.metadata.get("percent_used")
            if percent is not None:
                resources[metric_name] = percent

    return resources


def extract_database_info(status: SystemStatus) -> dict[str, Any]:
    """Extract database info from health status."""
    info: dict[str, Any] = {}

    aegis = status.components.get("aegis")
    if not aegis:
        return info

    components = aegis.sub_components.get("components")
    if not components:
        return info

    database = components.sub_components.get("database")
    if not database:
        return info

    info["status"] = database.status.value
    if database.metadata:
        info["table_count"] = database.metadata.get("table_count")
        info["total_rows"] = database.metadata.get("total_rows")
        info["file_size"] = database.metadata.get("file_size_human")

    return info


def extract_cache_info(status: SystemStatus) -> dict[str, Any]:
    """Extract cache/Redis info from health status."""
    info: dict[str, Any] = {}

    aegis = status.components.get("aegis")
    if not aegis:
        return info

    components = aegis.sub_components.get("components")
    if not components:
        return info

    cache = components.sub_components.get("cache")
    if not cache:
        return info

    info["status"] = cache.status.value
    if cache.metadata:
        info["hit_rate"] = cache.metadata.get("hit_rate_percent")
        info["total_keys"] = cache.metadata.get("total_keys")
        info["memory"] = cache.metadata.get("used_memory_human")

    return info


def extract_worker_info(status: SystemStatus) -> dict[str, Any]:
    """Extract worker queue info from health status."""
    info: dict[str, Any] = {}

    aegis = status.components.get("aegis")
    if not aegis:
        return info

    components = aegis.sub_components.get("components")
    if not components:
        return info

    worker = components.sub_components.get("worker")
    if not worker:
        return info

    info["status"] = worker.status.value
    if worker.metadata:
        info["total_queued"] = worker.metadata.get("total_queued", 0)
        info["total_completed"] = worker.metadata.get("total_completed", 0)
        info["total_failed"] = worker.metadata.get("total_failed", 0)
        info["total_ongoing"] = worker.metadata.get("total_ongoing", 0)
        info["failure_rate"] = worker.metadata.get("overall_failure_rate_percent")

    # Extract queue details from subcomponents
    queues_component = worker.sub_components.get("queues")
    if queues_component:
        if queues_component.metadata:
            info["active_workers"] = queues_component.metadata.get("active_workers")
            info["configured_queues"] = queues_component.metadata.get(
                "configured_queues"
            )

        # Get individual queue status
        queue_details: list[dict[str, Any]] = []
        for queue_name, queue in queues_component.sub_components.items():
            queue_info = {
                "name": queue_name,
                "status": queue.status.value,
                "healthy": queue.healthy,
            }
            if queue.metadata:
                queue_info["worker_alive"] = queue.metadata.get("worker_alive")
                queue_info["jobs_queued"] = queue.metadata.get("queued_jobs", 0)
                queue_info["jobs_completed"] = queue.metadata.get("jobs_completed", 0)
                queue_info["jobs_failed"] = queue.metadata.get("jobs_failed", 0)
                queue_info["jobs_ongoing"] = queue.metadata.get("jobs_ongoing", 0)
            queue_details.append(queue_info)

        if queue_details:
            info["queues"] = queue_details

    return info


def extract_scheduler_info(status: SystemStatus) -> dict[str, Any]:
    """Extract scheduler info from health status."""
    info: dict[str, Any] = {}

    aegis = status.components.get("aegis")
    if not aegis:
        return info

    components = aegis.sub_components.get("components")
    if not components:
        return info

    scheduler = components.sub_components.get("scheduler")
    if not scheduler:
        return info

    info["status"] = scheduler.status.value
    if scheduler.metadata:
        info["total_tasks"] = scheduler.metadata.get("total_tasks", 0)
        info["active_tasks"] = scheduler.metadata.get("active_tasks", 0)
        info["paused_tasks"] = scheduler.metadata.get("paused_tasks", 0)
        info["scheduler_state"] = scheduler.metadata.get("scheduler_state")
        info["upcoming_tasks"] = scheduler.metadata.get("upcoming_tasks", [])

    return info


def extract_ai_service_info(status: SystemStatus) -> dict[str, Any]:
    """Extract AI service info from health status."""
    info: dict[str, Any] = {}

    aegis = status.components.get("aegis")
    if not aegis:
        return info

    services = aegis.sub_components.get("services")
    if not services:
        return info

    ai = services.sub_components.get("ai")
    if not ai:
        return info

    info["status"] = ai.status.value
    info["message"] = ai.message
    if ai.metadata:
        info["provider"] = ai.metadata.get("provider")
        info["model"] = ai.metadata.get("model")

    return info


def extract_ollama_info(status: SystemStatus) -> dict[str, Any]:
    """Extract Ollama/Inference info from health status."""
    info: dict[str, Any] = {}

    aegis = status.components.get("aegis")
    if not aegis:
        return info

    components = aegis.sub_components.get("components")
    if not components:
        return info

    ollama = components.sub_components.get("ollama")
    if not ollama:
        return info

    info["status"] = ollama.status.value
    if ollama.metadata:
        info["version"] = ollama.metadata.get("version")
        info["installed_models"] = ollama.metadata.get("installed_models", [])
        info["running_models"] = ollama.metadata.get("running_models", [])
        info["total_vram_gb"] = ollama.metadata.get("total_vram_gb", 0)
        info["installed_count"] = ollama.metadata.get("installed_models_count", 0)
        info["running_count"] = ollama.metadata.get("running_models_count", 0)

    return info


def extract_issues(status: SystemStatus) -> list[tuple[str, str]]:
    """Extract unhealthy components with their error messages."""
    issues = []
    for name, component in status._get_all_components_flat():
        if not component.healthy:
            # Skip parent containers (focus on actual issues)
            if component.sub_components:
                continue
            # Get friendly name (last part of dotted path)
            friendly_name = name.split(".")[-1]
            issues.append((friendly_name, component.message))
    return issues
