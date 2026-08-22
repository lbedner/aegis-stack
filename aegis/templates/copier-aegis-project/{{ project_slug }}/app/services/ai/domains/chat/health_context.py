"""
Health context models for AI chat integration.

This module provides data structures for managing system health context injection
into AI chat conversations, giving Illiana awareness of system state.
"""

from datetime import UTC, datetime
from typing import Any

from app.services.system.models import SystemStatus
from pydantic import BaseModel, Field


def _format_relative_time(iso_time_str: str) -> str:
    """
    Format ISO datetime string to human readable relative time.

    Args:
        iso_time_str: ISO 8601 formatted datetime string

    Returns:
        Human-readable relative time ("in 5m", "in 2h", etc.)
    """
    if not iso_time_str:
        return ""

    try:
        if iso_time_str.endswith("Z"):
            next_run = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
        elif "+" in iso_time_str:
            next_run = datetime.fromisoformat(iso_time_str)
        else:
            next_run = datetime.fromisoformat(iso_time_str).replace(tzinfo=UTC)

        now = datetime.now(UTC)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)

        delta = next_run - now
        total_seconds = delta.total_seconds()

        if total_seconds < 0:
            return "past due"
        elif total_seconds < 60:
            return f"in {int(total_seconds)}s"
        elif total_seconds < 3600:
            return f"in {int(total_seconds / 60)}m"
        elif total_seconds < 86400:
            hours = total_seconds / 3600
            return f"in {int(hours)}h" if hours >= 2 else f"in {hours:.1f}h"
        else:
            return f"in {int(total_seconds / 86400)}d"
    except Exception:
        return ""


class HealthContext(BaseModel):
    """
    Context from system health for injection into AI prompts.

    Holds system status and provides formatting methods for prompt injection
    and metadata storage.
    """

    status: SystemStatus = Field(..., description="System health status")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When health was fetched",
    )

    def format_for_prompt(self, verbose: bool = False, compact: bool = False) -> str:
        """
        Format health data for injection into system prompt.

        Args:
            verbose: Whether to include detailed component info
            compact: Whether to use ultra-compact format for smaller models (Ollama)

        Returns:
            Formatted string for prompt injection
        """
        # Ultra-compact mode for Ollama and smaller models
        if compact:
            return self._format_compact()

        lines = []

        # Header with overall health
        healthy_count = len(self.status.healthy_components)
        total_count = len(self.status._get_all_components_flat())
        health_pct = self.status.health_percentage

        status_emoji = "OK" if self.status.overall_healthy else "DEGRADED"
        health_str = f"{health_pct:.0f}% - {healthy_count}/{total_count} components"
        lines.append(f"Health: {status_emoji} ({health_str})")

        # System resources (CPU, Memory, Disk)
        resources = self._extract_system_resources()
        if resources:
            resource_parts = []
            if "cpu" in resources:
                resource_parts.append(f"CPU {resources['cpu']:.0f}%")
            if "memory" in resources:
                resource_parts.append(f"Mem {resources['memory']:.0f}%")
            if "disk" in resources:
                resource_parts.append(f"Disk {resources['disk']:.0f}%")
            if resource_parts:
                lines.append(f"Resources: {' | '.join(resource_parts)}")

        # Database status
        db_info = self._extract_database_info()
        if db_info:
            db_parts = [db_info["status"]]
            if db_info.get("table_count"):
                db_parts.append(f"{db_info['table_count']} tables")
            if db_info.get("total_rows"):
                db_parts.append(f"{db_info['total_rows']:,} rows")
            lines.append(f"Database: {', '.join(db_parts)}")

        # Cache status
        cache_info = self._extract_cache_info()
        if cache_info:
            cache_parts = [cache_info["status"]]
            if cache_info.get("hit_rate") is not None:
                cache_parts.append(f"hit rate {cache_info['hit_rate']:.0f}%")
            if cache_info.get("total_keys"):
                cache_parts.append(f"{cache_info['total_keys']:,} keys")
            lines.append(f"Cache: {', '.join(cache_parts)}")

        # Worker status
        worker_info = self._extract_worker_info()
        if worker_info:
            # Header with active/total workers
            active = worker_info.get("active_workers", 0)
            configured = worker_info.get("configured_queues", 0)
            if configured:
                lines.append(f"Workers: {active}/{configured} active")
            else:
                lines.append(f"Workers: {active} active")

            # Queue details
            queues = worker_info.get("queues", [])
            if queues:
                queue_statuses = []
                for q in queues:
                    name = q["name"]
                    if q.get("worker_alive"):
                        # Determine if busy or idle
                        ongoing = q.get("jobs_ongoing", 0)
                        status = "busy" if ongoing > 0 else "idle"
                    else:
                        status = "offline"
                    queue_statuses.append(f"{name} ({status})")
                lines.append(f"  Queues: {', '.join(queue_statuses)}")

            # Job stats
            total_queued = worker_info.get("total_queued", 0)
            total_completed = worker_info.get("total_completed", 0)
            total_failed = worker_info.get("total_failed", 0)
            total_ongoing = worker_info.get("total_ongoing", 0)
            job_parts = []
            if total_ongoing:
                job_parts.append(f"{total_ongoing} running")
            job_parts.append(f"{total_queued} queued")
            job_parts.append(f"{total_completed} completed")
            if total_failed:
                job_parts.append(f"{total_failed} failed")
            lines.append(f"  Jobs: {', '.join(job_parts)}")

        # Scheduler status
        scheduler_info = self._extract_scheduler_info()
        if scheduler_info:
            total = scheduler_info.get("total_tasks", 0)
            active = scheduler_info.get("active_tasks", 0)
            paused = scheduler_info.get("paused_tasks", 0)

            if total:
                if paused:
                    lines.append(
                        f"Scheduler: {active}/{total} active ({paused} paused)"
                    )
                else:
                    lines.append(f"Scheduler: {active} active tasks")
            else:
                lines.append("Scheduler: No tasks configured")

            # Show upcoming tasks (next 3 for brevity)
            upcoming = scheduler_info.get("upcoming_tasks", [])
            if upcoming:
                task_strs = []
                for task in upcoming[:3]:
                    name = task.get("name", task.get("job_id", "Unknown"))
                    schedule = task.get("schedule", "")
                    next_run = task.get("next_run", "")
                    relative_time = _format_relative_time(next_run)
                    if relative_time:
                        task_strs.append(f"{name} ({schedule}, {relative_time})")
                    else:
                        task_strs.append(f"{name} ({schedule})")
                lines.append(f"  Next: {', '.join(task_strs)}")

        # AI service status
        ai_info = self._extract_ai_service_info()
        if ai_info:
            ai_line = f"AI: {ai_info['status']}"
            if ai_info.get("provider"):
                ai_line += f" | Provider: {ai_info['provider']}"
            if ai_info.get("model"):
                ai_line += f" | Model: {ai_info['model']}"
            lines.append(ai_line)

        # Ollama/Inference status (detailed model info)
        ollama_info = self._extract_ollama_info()
        if ollama_info:
            version = ollama_info.get("version", "")
            version_str = f" v{version}" if version else ""
            lines.append(f"Inference: Ollama{version_str}")

            # Installed models with details
            installed = ollama_info.get("installed_models", [])
            if installed:
                model_strs = []
                for m in installed[:5]:  # Limit to 5
                    name = m.get("name", "unknown")
                    size = m.get("size_gb", 0)
                    details = m.get("details", {})
                    quant = details.get("quantization_level", "")
                    params = details.get("parameter_size", "")

                    # Format: "qwen2.5:7b 4-bit 7.6B 4.7G"
                    parts = [name]
                    if quant and quant.startswith("Q"):
                        parts.append(f"{quant[1]}-bit")
                    if params:
                        parts.append(params)
                    parts.append(f"{size:.1f}G")
                    model_strs.append(" ".join(parts))

                lines.append(f"  Installed: {', '.join(model_strs)}")

            # Running/warm models with VRAM
            running = ollama_info.get("running_models", [])
            total_vram = ollama_info.get("total_vram_gb", 0)
            if running:
                warm_names = [m.get("name", "unknown") for m in running]
                lines.append(
                    f"  Loaded: {', '.join(warm_names)} ({total_vram:.1f}G VRAM)"
                )
            else:
                lines.append("  Loaded: none (cold)")

        # Unhealthy components with details
        issues = self._extract_issues()
        if issues:
            lines.append("Issues:")
            for name, message in issues[:5]:
                lines.append(f"  - {name}: {message}")

        return "\n".join(lines)

    def _format_compact(self) -> str:
        """
        Format health data in compact mode for smaller models.

        Returns:
            Multi-line compact summary with all key metrics
        """
        lines = []

        # Core metrics
        healthy_count = len(self.status.healthy_components)
        total_count = len(self.status._get_all_components_flat())
        health_pct = self.status.health_percentage
        status = "OK" if self.status.overall_healthy else "DEGRADED"
        lines.append(
            f"Health: {status} ({health_pct:.0f}%, {healthy_count}/{total_count})"
        )

        # System resources
        resources = self._extract_system_resources()
        res_parts = []
        if resources.get("cpu") is not None:
            res_parts.append(f"CPU {resources['cpu']:.0f}%")
        if resources.get("memory") is not None:
            res_parts.append(f"Mem {resources['memory']:.0f}%")
        if resources.get("disk") is not None:
            res_parts.append(f"Disk {resources['disk']:.0f}%")
        if res_parts:
            lines.append(f"Resources: {' | '.join(res_parts)}")

        # Database
        db_info = self._extract_database_info()
        if db_info:
            db_parts = [db_info.get("status", "unknown")]
            if db_info.get("table_count"):
                db_parts.append(f"{db_info['table_count']} tables")
            if db_info.get("total_rows"):
                db_parts.append(f"{db_info['total_rows']:,} rows")
            lines.append(f"Database: {', '.join(db_parts)}")

        # Cache
        cache_info = self._extract_cache_info()
        if cache_info:
            cache_parts = [cache_info.get("status", "unknown")]
            if cache_info.get("hit_rate") is not None:
                cache_parts.append(f"{cache_info['hit_rate']:.0f}% hit rate")
            if cache_info.get("total_keys"):
                cache_parts.append(f"{cache_info['total_keys']:,} keys")
            lines.append(f"Cache: {', '.join(cache_parts)}")

        # Workers
        worker_info = self._extract_worker_info()
        if worker_info:
            active = worker_info.get("active_workers", 0)
            configured = worker_info.get("configured_queues", 0)
            queued = worker_info.get("total_queued", 0)
            completed = worker_info.get("total_completed", 0)
            lines.append(
                f"Workers: {active}/{configured} active, "
                f"{queued} queued, {completed} completed"
            )

        # Scheduler
        scheduler_info = self._extract_scheduler_info()
        if scheduler_info:
            total = scheduler_info.get("total_tasks", 0)
            active = scheduler_info.get("active_tasks", 0)
            lines.append(f"Scheduler: {active}/{total} tasks active")

        # AI service
        ai_info = self._extract_ai_service_info()
        if ai_info:
            ai_status = ai_info.get("status", "unknown")
            ai_provider = ai_info.get("provider", "?")
            ai_model = ai_info.get("model", "?")
            lines.append(f"AI: {ai_status}, {ai_provider}/{ai_model}")

        # Ollama
        ollama_info = self._extract_ollama_info()
        if ollama_info:
            installed = ollama_info.get("installed_count", 0)
            running = ollama_info.get("running_count", 0)
            vram = ollama_info.get("total_vram_gb", 0)
            lines.append(
                f"Ollama: {installed} models, {running} loaded, {vram:.1f}G VRAM"
            )

        # Issues with actual messages
        issues = self._extract_issues()
        if issues:
            lines.append(f"Issues ({len(issues)}):")
            for name, message in issues[:5]:
                lines.append(f"  - {name}: {message}")

        return "\n".join(lines)

    def _extract_system_resources(self) -> dict[str, float]:
        """Extract CPU, memory, disk percentages from health status."""
        resources: dict[str, float] = {}

        # Navigate to backend component which contains system metrics
        aegis = self.status.components.get("aegis")
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

    def _extract_database_info(self) -> dict[str, Any]:
        """Extract database info from health status."""
        info: dict[str, Any] = {}

        aegis = self.status.components.get("aegis")
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

    def _extract_cache_info(self) -> dict[str, Any]:
        """Extract cache/Redis info from health status."""
        info: dict[str, Any] = {}

        aegis = self.status.components.get("aegis")
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

    def _extract_worker_info(self) -> dict[str, Any]:
        """Extract worker queue info from health status."""
        info: dict[str, Any] = {}

        aegis = self.status.components.get("aegis")
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
                    queue_info["jobs_completed"] = queue.metadata.get(
                        "jobs_completed", 0
                    )
                    queue_info["jobs_failed"] = queue.metadata.get("jobs_failed", 0)
                    queue_info["jobs_ongoing"] = queue.metadata.get("jobs_ongoing", 0)
                queue_details.append(queue_info)

            if queue_details:
                info["queues"] = queue_details

        return info

    def _extract_scheduler_info(self) -> dict[str, Any]:
        """Extract scheduler info from health status."""
        info: dict[str, Any] = {}

        aegis = self.status.components.get("aegis")
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

    def _extract_ai_service_info(self) -> dict[str, Any]:
        """Extract AI service info from health status."""
        info: dict[str, Any] = {}

        aegis = self.status.components.get("aegis")
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

    def _extract_ollama_info(self) -> dict[str, Any]:
        """Extract Ollama/Inference info from health status."""
        info: dict[str, Any] = {}

        aegis = self.status.components.get("aegis")
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

    def _extract_issues(self) -> list[tuple[str, str]]:
        """Extract unhealthy components with their error messages."""
        issues = []
        for name, component in self.status._get_all_components_flat():
            if not component.healthy:
                # Skip parent containers (focus on actual issues)
                if component.sub_components:
                    continue
                # Get friendly name (last part of dotted path)
                friendly_name = name.split(".")[-1]
                issues.append((friendly_name, component.message))
        return issues

    def to_metadata(self) -> dict[str, Any]:
        """
        Convert health context to metadata format for storage in response.

        Returns:
            Summary metadata dictionary
        """
        return {
            "overall_healthy": self.status.overall_healthy,
            "health_percentage": self.status.health_percentage,
            "healthy_count": len(self.status.healthy_components),
            "total_count": len(self.status._get_all_components_flat()),
            "unhealthy_components": self.status.unhealthy_components[:5],
            "timestamp": self.timestamp.isoformat(),
        }


__all__ = ["HealthContext"]
