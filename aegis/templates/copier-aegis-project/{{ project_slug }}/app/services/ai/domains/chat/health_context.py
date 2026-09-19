"""
Health context models for AI chat integration.

This module provides data structures for managing system health context injection
into AI chat conversations, giving Illiana awareness of system state.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.services.system.models import SystemStatus

from .health_extract import (
    extract_ai_service_info,
    extract_cache_info,
    extract_database_info,
    extract_issues,
    extract_ollama_info,
    extract_scheduler_info,
    extract_system_resources,
    extract_worker_info,
)


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
        resources = extract_system_resources(self.status)
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
        db_info = extract_database_info(self.status)
        if db_info:
            db_parts = [db_info["status"]]
            if db_info.get("table_count"):
                db_parts.append(f"{db_info['table_count']} tables")
            if db_info.get("total_rows"):
                db_parts.append(f"{db_info['total_rows']:,} rows")
            lines.append(f"Database: {', '.join(db_parts)}")

        # Cache status
        cache_info = extract_cache_info(self.status)
        if cache_info:
            cache_parts = [cache_info["status"]]
            if cache_info.get("hit_rate") is not None:
                cache_parts.append(f"hit rate {cache_info['hit_rate']:.0f}%")
            if cache_info.get("total_keys"):
                cache_parts.append(f"{cache_info['total_keys']:,} keys")
            lines.append(f"Cache: {', '.join(cache_parts)}")

        # Worker status
        worker_info = extract_worker_info(self.status)
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
        scheduler_info = extract_scheduler_info(self.status)
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
        ai_info = extract_ai_service_info(self.status)
        if ai_info:
            ai_line = f"AI: {ai_info['status']}"
            if ai_info.get("provider"):
                ai_line += f" | Provider: {ai_info['provider']}"
            if ai_info.get("model"):
                ai_line += f" | Model: {ai_info['model']}"
            lines.append(ai_line)

        # Ollama/Inference status (detailed model info)
        ollama_info = extract_ollama_info(self.status)
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
        issues = extract_issues(self.status)
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
        resources = extract_system_resources(self.status)
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
        db_info = extract_database_info(self.status)
        if db_info:
            db_parts = [db_info.get("status", "unknown")]
            if db_info.get("table_count"):
                db_parts.append(f"{db_info['table_count']} tables")
            if db_info.get("total_rows"):
                db_parts.append(f"{db_info['total_rows']:,} rows")
            lines.append(f"Database: {', '.join(db_parts)}")

        # Cache
        cache_info = extract_cache_info(self.status)
        if cache_info:
            cache_parts = [cache_info.get("status", "unknown")]
            if cache_info.get("hit_rate") is not None:
                cache_parts.append(f"{cache_info['hit_rate']:.0f}% hit rate")
            if cache_info.get("total_keys"):
                cache_parts.append(f"{cache_info['total_keys']:,} keys")
            lines.append(f"Cache: {', '.join(cache_parts)}")

        # Workers
        worker_info = extract_worker_info(self.status)
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
        scheduler_info = extract_scheduler_info(self.status)
        if scheduler_info:
            total = scheduler_info.get("total_tasks", 0)
            active = scheduler_info.get("active_tasks", 0)
            lines.append(f"Scheduler: {active}/{total} tasks active")

        # AI service
        ai_info = extract_ai_service_info(self.status)
        if ai_info:
            ai_status = ai_info.get("status", "unknown")
            ai_provider = ai_info.get("provider", "?")
            ai_model = ai_info.get("model", "?")
            lines.append(f"AI: {ai_status}, {ai_provider}/{ai_model}")

        # Ollama
        ollama_info = extract_ollama_info(self.status)
        if ollama_info:
            installed = ollama_info.get("installed_count", 0)
            running = ollama_info.get("running_count", 0)
            vram = ollama_info.get("total_vram_gb", 0)
            lines.append(
                f"Ollama: {installed} models, {running} loaded, {vram:.1f}G VRAM"
            )

        # Issues with actual messages
        issues = extract_issues(self.status)
        if issues:
            lines.append(f"Issues ({len(issues)}):")
            for name, message in issues[:5]:
                lines.append(f"  - {name}: {message}")

        return "\n".join(lines)

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
