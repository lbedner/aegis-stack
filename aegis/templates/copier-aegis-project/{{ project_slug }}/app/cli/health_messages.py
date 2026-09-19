"""Turning a component's raw health string into readable English."""

import re

from app.cli import theme
from app.i18n import t

console = theme.console()


_HEALTH_MSG_EXACT: dict[str, str] = {
    "Aegis Stack application": "health.msg.aegis_ok",
    "Aegis Stack has issues": "health.msg.aegis_issues",
    "Some components have issues": "health.msg.components_issues",
    "Some services have issues": "health.msg.services_issues",
    "System container metrics": "health.msg.system_ok",
    "System container has issues": "health.msg.system_issues",
    "Database connection successful": "health.msg.db_ok",
    "Database module not available": "health.msg.db_module_missing",
    "PostgreSQL server not reachable": "health.msg.db_not_reachable",
    "PostgreSQL authentication failed": "health.msg.db_auth_failed",
    "PostgreSQL database does not exist": "health.msg.db_not_exist",
    "Database not initialized - file does not exist": "health.msg.db_not_init",
    "Database file not accessible": "health.msg.db_not_accessible",
    "Redis cache connection and operations successful": "health.msg.cache_ok",
    "Cache library not installed": "health.msg.cache_not_installed",
    "No active workers": "health.msg.no_active_workers",
    "idle": "health.msg.idle",
    "configured - no functions defined": "health.msg.no_functions",
    "Auth service configured and ready": "health.msg.auth_ok",
    "AI service is disabled": "health.msg.ai_disabled",
    "No communication providers configured": "health.msg.comms_none",
    "Communications service fully configured": "health.msg.comms_ok",
    "Ollama server not reachable": "health.msg.ollama_not_reachable",
    "Ollama running but no models installed": "health.msg.ollama_no_models",
    "worker offline - no health check data": "health.msg.worker_offline",
}


_HEALTH_MSG_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # (compiled_regex, i18n_key, group_mapping)
    (re.compile(r"^(\d+) components available$"), "health.msg.components_ok", "count"),
    (re.compile(r"^(\d+) services available$"), "health.msg.services_ok", "count"),
    (re.compile(r"^Memory usage: ([\d.]+)%$"), "health.msg.memory_usage", "pct"),
    (re.compile(r"^Disk usage: ([\d.]+)%$"), "health.msg.disk_usage", "pct"),
    (re.compile(r"^CPU usage: ([\d.]+)%$"), "health.msg.cpu_usage", "pct"),
    (
        re.compile(r"^Scheduler running with (\d+) tasks?$"),
        "health.msg.scheduler_running",
        "count",
    ),
    (re.compile(r"^Database connection failed"), "health.msg.db_failed", ""),
    (re.compile(r"^FastAPI backend active"), "health.msg.backend_active", ""),
    (
        re.compile(r"^(arq|TaskIQ|Dramatiq) worker infrastructure"),
        "health.msg.worker_infra",
        "backend",
    ),
    (
        re.compile(r"^(\d+)/(\d+) workers? active$"),
        "health.msg.workers_active",
        "active,total",
    ),
    (
        re.compile(r"^(\d+) functional queues configured"),
        "health.msg.queues_configured",
        "count",
    ),
    (
        re.compile(r"^\((\d+) (?:active|with consumers|with heartbeats)\)$"),
        "health.msg.queues_active",
        "count",
    ),
    (re.compile(r"^(\d+) processing$"), "health.msg.processing", "count"),
    (re.compile(r"^(\d+) queued$"), "health.msg.queued", "count"),
    (re.compile(r"^(\d+) completed$"), "health.msg.completed", "count"),
    (re.compile(r"^(\d+) failed \(([\d.]+)%\)$"), "health.msg.failed", "count,pct"),
    (re.compile(r"^AI service ready"), "health.msg.ai_ready", ""),
    (
        re.compile(r"^Comms service partially configured"),
        "health.msg.comms_partial",
        "",
    ),
]


_QUEUE_DESC_MAP: dict[str, str] = {
    "Load testing and performance testing": "health.msg.queue.load_test",
    "Image and file processing": "health.msg.queue.media",
    "System maintenance and monitoring tasks": "health.msg.queue.system",
}


def _translate_single_part(part: str) -> str:
    """Translate a single status part (used for comma-separated segments)."""
    key = _HEALTH_MSG_EXACT.get(part)
    if key:
        return t(key)
    for pattern, i18n_key, groups in _HEALTH_MSG_PATTERNS:
        match = pattern.match(part)
        if match:
            if not groups:
                return t(i18n_key)
            group_names = groups.split(",")
            kwargs = {name: match.group(i + 1) for i, name in enumerate(group_names)}
            return t(i18n_key, **kwargs)
    return part


def _translate_health_msg(msg: str) -> str:
    """Translate a health API message at display time."""
    # Try exact match first
    key = _HEALTH_MSG_EXACT.get(msg)
    if key:
        return t(key)

    # Try pattern matching
    for pattern, i18n_key, groups in _HEALTH_MSG_PATTERNS:
        match = pattern.match(msg)
        if match:
            if not groups:
                return t(i18n_key)
            group_names = groups.split(",")
            kwargs = {name: match.group(i + 1) for i, name in enumerate(group_names)}
            return t(i18n_key, **kwargs)

    # Try composite "description: status" messages (e.g., queue messages)
    if ": " in msg:
        desc, status = msg.split(": ", 1)
        desc_key = _QUEUE_DESC_MAP.get(desc)
        # Translate each comma-separated status part individually
        status_parts = [p.strip() for p in status.split(", ")]
        translated_parts = []
        for part in status_parts:
            translated = _translate_single_part(part)
            translated_parts.append(translated)
        status = ", ".join(translated_parts)
        if desc_key:
            return f"{t(desc_key)}：{status}"

    # No translation found — return original
    return msg
