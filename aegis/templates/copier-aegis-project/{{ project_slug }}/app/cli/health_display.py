"""Drawing the health report: icons, counts, and the component tree."""

from collections import Counter
import json
from typing import Any

from rich.panel import Panel

from app.cli import theme
from app.cli.health_messages import _translate_health_msg
from app.core.constants import CLI, ComponentName
from app.i18n import t
from app.services.system.models import (
    ComponentStatus,
    ComponentStatusType,
    DetailedHealthResponse,
)
from app.services.system.ui import get_status_color_name, get_status_icon

console = theme.console()


def _theme_status_style(semantic_color: str) -> str:
    """Map a semantic status color name to a brand Rich markup style.

    Color encodes state: teal=healthy, amber=warning, red=error; info and
    anything else is a non-problem sub-state, rendered dim.
    """
    return {
        "green": theme.ACCENT,
        "yellow": theme.WARNING,
        "red": theme.ERROR,
    }.get(semantic_color, "dim")


def _get_status_icon_and_color(status: ComponentStatusType) -> tuple[str, str]:
    """Get the appropriate icon and color for a component status (shared mapping)."""
    return get_status_icon(status), _theme_status_style(get_status_color_name(status))


def _count_status_types(components: dict[str, ComponentStatus]) -> Counter[str]:
    """Components by status value; a status none has counts 0."""
    return Counter(component.status.value for component in components.values())


def _format_status_breakdown(counts: dict[str, int]) -> str:
    """
    Format status counts into a readable string.

    Shows: "X healthy, Y warnings, Z info" (omits unhealthy and zero counts)
    Returns color based on status mix.
    """
    parts = []

    if counts["healthy"] > 0:
        parts.append(t("health.count_healthy", count=counts["healthy"]))
    if counts["warning"] > 0:
        if counts["warning"] > 1:
            parts.append(t("health.count_warnings", count=counts["warning"]))
        else:
            parts.append(t("health.count_warning", count=counts["warning"]))
    if counts["info"] > 0:
        parts.append(t("health.count_info", count=counts["info"]))
    if counts["unhealthy"] > 0:
        parts.append(t("health.count_unhealthy", count=counts["unhealthy"]))

    return ", ".join(parts) if parts else t("health.zero_components")


def _get_status_color(counts: dict[str, int]) -> str:
    """Get brand markup style based on status breakdown."""
    if counts["unhealthy"] > 0:
        return theme.ERROR
    elif counts["warning"] > 0:
        return theme.WARNING
    elif counts["info"] > 0:
        return "dim"
    else:
        return theme.ACCENT


def _is_scheduler_metadata(metadata: dict[str, Any]) -> bool:
    """Check if metadata contains scheduler-specific task information."""
    return "total_tasks" in metadata and "upcoming_tasks" in metadata


def _display_scheduler_metadata(metadata: dict[str, Any], tree_indent: str) -> None:
    """Display scheduler metadata in a structured, readable format."""
    # Task statistics
    total_tasks = metadata.get("total_tasks", 0)
    active_tasks = metadata.get("active_tasks", 0)
    paused_tasks = metadata.get("paused_tasks", 0)

    console.print(f"{tree_indent}[dim]{t('health.task_statistics')}[/dim]")
    stats_line = t(
        "health.task_stats_line",
        total=total_tasks,
        active=active_tasks,
        paused=paused_tasks,
    )
    console.print(f"{tree_indent}  [dim]• {stats_line}[/dim]")

    # Upcoming tasks
    upcoming_tasks = metadata.get("upcoming_tasks", [])
    if upcoming_tasks:
        console.print(f"{tree_indent}[dim]{t('health.upcoming_tasks')}[/dim]")
        for task in upcoming_tasks:
            task_name = task.get("name", task.get("id", t("shared.unknown")))
            next_run = task.get("next_run", t("shared.unknown"))

            # Format next run time more human-readable
            if next_run and next_run != t("shared.unknown"):
                try:
                    from datetime import datetime

                    if next_run.endswith("+00:00") or next_run.endswith("Z"):
                        dt = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
                        formatted_time = dt.strftime("%Y-%m-%d %H:%M UTC")
                    else:
                        formatted_time = next_run
                except Exception:
                    formatted_time = next_run
            else:
                formatted_time = t("shared.unknown")

            next_run_line = t(
                "health.task_next_run", name=task_name, time=formatted_time
            )
            console.print(f"{tree_indent}  [dim]• {next_run_line}[/dim]")
    else:
        console.print(f"{tree_indent}[dim]{t('health.no_upcoming_tasks')}[/dim]")


def _display_metadata(name: str, metadata: dict[str, Any], indent: str) -> None:
    """A part's metadata: the scheduler's tasks, anything else as JSON."""
    if name == ComponentName.SCHEDULER and _is_scheduler_metadata(metadata):
        _display_scheduler_metadata(metadata, indent)
        return
    metadata_str = json.dumps(metadata, separators=(",", ":"))
    max_length = CLI.MAX_METADATA_DISPLAY_LENGTH
    if len(metadata_str) > max_length:
        metadata_str = metadata_str[: max_length - 3] + "..."
    console.print(f"{indent}[dim]({metadata_str})[/dim]")


def _display_sub_components(
    sub_components: dict[str, ComponentStatus], detailed: bool, indent: str
) -> None:
    """Recursively display sub-components, each level under ``indent``."""
    sub_items = list(sub_components.items())

    for i, (sub_name, sub_component) in enumerate(sub_items):
        sub_icon, sub_color = _get_status_icon_and_color(sub_component.status)

        # Tree connector: ├── for middle items, └── for last item
        is_last = i == len(sub_items) - 1
        tree_connector = f"{indent}└── " if is_last else f"{indent}├── "
        # What hangs below keeps this level's line going while more follow.
        tree_indent = f"{indent}    " if is_last else f"{indent}│   "

        sub_line = f"{tree_connector}[{sub_color}]{sub_icon} {sub_name}[/{sub_color}]"
        if detailed and sub_component.response_time_ms is not None:
            sub_line += f" ([dim]{sub_component.response_time_ms:.1f}ms[/dim])"
        sub_line += f"    {_translate_health_msg(sub_component.message)}"
        console.print(sub_line)

        if sub_component.sub_components:
            _display_sub_components(sub_component.sub_components, detailed, tree_indent)
        elif detailed and sub_component.metadata:
            _display_metadata(sub_name, sub_component.metadata, tree_indent)


def _group(components: dict[str, ComponentStatus], name: str) -> dict[str, ComponentStatus]:
    """The parts under the root's ``name`` group ("components", "services")."""
    aegis = components.get("aegis")
    group = aegis.sub_components.get(name) if aegis else None
    return group.sub_components if group else {}


def _group_line(label_key: str, group: dict[str, ComponentStatus]) -> str:
    """A group's line in the panel: its label and its status breakdown."""
    counts = _count_status_types(group)
    color = _get_status_color(counts)
    breakdown = _format_status_breakdown(counts)
    return f"{t(label_key)} [bold {color}]{breakdown}[/bold {color}]"


def _display_health_status(
    health_data: DetailedHealthResponse, detailed: bool = False
) -> None:
    """Display health status with rich formatting."""

    components = health_data.components

    _, overall_color = _get_status_icon_and_color(health_data.status)
    status_label = t(f"health.{health_data.status.value}")
    title = f"{t('health.title')} - {status_label}"

    panel_content = [
        f"{t('health.overall_status')} [bold {overall_color}]"
        + status_label
        + f"[/bold {overall_color}]",
        f"{t('health.health_percentage')} [bold]"
        f"{health_data.health_percentage:.{CLI.HEALTH_PERCENTAGE_DECIMALS}f}%[/bold]",
        _group_line("health.components_label", _group(components, "components")),
    ]

    # Add service information
    services = _group(components, "services")
    if services:
        panel_content.append(_group_line("health.services_label", services))

    panel_content.append(f"{t('health.timestamp_label')} {health_data.timestamp}")

    console.print(
        Panel("\n".join(panel_content), title=title, border_style=overall_color)
    )

    # Component and Service Tree Display
    tree_title = t("health.component_tree")
    if health_data.has_services:
        tree_title = t("health.component_service_tree")
    console.print(f"\n[bold]{tree_title}:[/bold]")

    # Sort components: unhealthy first, then by name
    sorted_components = sorted(components.items(), key=lambda x: (x[1].healthy, x[0]))

    for name, component in sorted_components:
        status_icon, status_color = _get_status_icon_and_color(component.status)

        # Display main component
        component_line = f"[{status_color}]{status_icon} {name}[/{status_color}]"
        if detailed and component.response_time_ms is not None:
            component_line += f" ([dim]{component.response_time_ms:.1f}ms[/dim])"
        component_line += f"    {_translate_health_msg(component.message)}"
        console.print(component_line)

        # Display sub-components with tree structure (recursive)
        if component.sub_components:
            _display_sub_components(component.sub_components, detailed, "   ")
        elif detailed and component.metadata:
            _display_metadata(name, component.metadata, "    ")

    # System information (only in detailed mode)
    if detailed and health_data.system_info:
        sys_info_content = []
        for key, value in health_data.system_info.items():
            label_key = f"health.sysinfo.{key}"
            label = t(label_key)
            if label == label_key:
                label = key.replace("_", " ").title()
            sys_info_content.append(t("health.labeled", label=label, value=value))

        console.print(
            Panel(
                "\n".join(sys_info_content),
                title=t("health.system_info"),
                border_style="dim",
            )
        )
