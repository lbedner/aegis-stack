"""Drawing the health report: icons, counts, and the component tree."""

import json
from typing import Any

from rich.panel import Panel

from app.cli import theme
from app.cli.health_messages import _translate_health_msg
from app.core.constants import CLI
from app.i18n import t
from app.services.system.models import (
    ComponentStatusType,
    DetailedHealthResponse,
    HealthResponse,
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


def _count_status_types(components: dict[str, Any]) -> dict[str, int]:
    """
    Count components by status type.

    Returns dict with counts for: healthy, warning, info, unhealthy
    """
    counts = {
        "healthy": 0,
        "warning": 0,
        "info": 0,
        "unhealthy": 0,
    }

    for component in components.values():
        if hasattr(component, "status"):
            status = component.status
            if status == ComponentStatusType.HEALTHY:
                counts["healthy"] += 1
            elif status == ComponentStatusType.WARNING:
                counts["warning"] += 1
            elif status == ComponentStatusType.INFO:
                counts["info"] += 1
            elif status == ComponentStatusType.UNHEALTHY:
                counts["unhealthy"] += 1

    return counts


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


def _display_scheduler_metadata(
    metadata: dict[str, Any], base_indent: str, is_last: bool, detailed: bool = False
) -> None:
    """Display scheduler metadata in a structured, readable format."""
    tree_indent = f"{base_indent}    " if is_last else f"{base_indent}│   "

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
        # In detailed mode, show all tasks. Otherwise show top 3
        max_tasks = len(upcoming_tasks) if detailed else 3
        for task in upcoming_tasks[:max_tasks]:
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

        # Show "and X more..." if there are more tasks (only in non-detailed mode)
        if not detailed and len(upcoming_tasks) > 3:
            remaining = len(upcoming_tasks) - 3
            task_word = (
                t("health.task_word") if remaining == 1 else t("health.tasks_word")
            )
            more_line = t("health.more_tasks", count=remaining, word=task_word)
            console.print(f"{tree_indent}  [dim]• {more_line}[/dim]")
    else:
        console.print(f"{tree_indent}[dim]{t('health.no_upcoming_tasks')}[/dim]")


def _display_sub_components(
    sub_components: dict[str, Any], detailed: bool, level: int
) -> None:
    """Recursively display sub-components with appropriate tree indentation."""
    sub_items = list(sub_components.items())

    # Calculate tree indentation based on level
    base_indent = "   " * level

    for i, (sub_name, sub_component) in enumerate(sub_items):
        sub_icon, sub_color = _get_status_icon_and_color(sub_component.status)

        # Tree connector: ├── for middle items, └── for last item
        is_last = i == len(sub_items) - 1
        tree_connector = f"{base_indent}└── " if is_last else f"{base_indent}├── "

        sub_line = f"{tree_connector}[{sub_color}]{sub_icon} {sub_name}[/{sub_color}]"
        if detailed and sub_component.response_time_ms is not None:
            sub_line += f" ([dim]{sub_component.response_time_ms:.1f}ms[/dim])"
        sub_line += f"    {_translate_health_msg(sub_component.message)}"
        console.print(sub_line)

        # Recursively display sub-sub-components
        if hasattr(sub_component, "sub_components") and sub_component.sub_components:
            _display_sub_components(sub_component.sub_components, detailed, level + 1)

        # Show metadata for sub-components if detailed and available
        elif detailed and sub_component.metadata:
            # Special handling for scheduler component
            if sub_name == "scheduler" and _is_scheduler_metadata(
                sub_component.metadata
            ):
                _display_scheduler_metadata(
                    sub_component.metadata, base_indent, is_last, detailed
                )
            else:
                # Generic metadata display for other components
                metadata_str = json.dumps(sub_component.metadata, separators=(",", ":"))
                max_length = CLI.MAX_METADATA_DISPLAY_LENGTH
                if len(metadata_str) > max_length:
                    metadata_str = metadata_str[: max_length - 3] + "..."
                # Adjust tree indent based on whether this is the last item
                tree_indent = f"{base_indent}    " if is_last else f"{base_indent}│   "
                console.print(f"{tree_indent}[dim]({metadata_str})[/dim]")


def _display_health_status(
    health_data: HealthResponse | DetailedHealthResponse, detailed: bool = False
) -> None:
    """Display health status with rich formatting."""

    # Extract data from Pydantic model
    overall_healthy = health_data.healthy
    components = health_data.components
    timestamp = health_data.timestamp

    # Use health percentage from API response if available (DetailedHealthResponse)
    # Otherwise calculate from top-level components (HealthResponse)
    if hasattr(health_data, "health_percentage"):
        health_percentage = health_data.health_percentage
        # For detailed response, use the component counts from API
        if hasattr(health_data, "healthy_components"):
            if hasattr(health_data, "unhealthy_components"):
                healthy_count = len(health_data.healthy_components)
                total_count = len(health_data.healthy_components) + len(
                    health_data.unhealthy_components
                )
            else:
                # HealthResponse doesn't have detailed component lists
                healthy_count = 1 if health_data.healthy else 0
                total_count = 1
        else:
            # Fallback for detailed response without component lists
            healthy_count = sum(1 for comp in components.values() if comp.healthy)
            total_count = len(components)
    else:
        # Basic health response - count main sub-components for better overview
        if components and "aegis" in components:
            aegis_component = components["aegis"]
            if (
                hasattr(aegis_component, "sub_components")
                and aegis_component.sub_components
            ):
                healthy_count = sum(
                    1
                    for comp in aegis_component.sub_components.values()
                    if comp.healthy
                )
                total_count = len(aegis_component.sub_components)
                health_percentage = (
                    (healthy_count / total_count) * 100 if total_count > 0 else 100.0
                )
            else:
                # Fallback to aegis component only
                healthy_count = 1 if aegis_component.healthy else 0
                total_count = 1
                health_percentage = 100.0 if aegis_component.healthy else 0.0
        else:
            # No components or no aegis component
            healthy_count = 0
            total_count = 0
            health_percentage = 0.0

    overall_color = theme.ACCENT if overall_healthy else theme.ERROR

    status_label = t("health.healthy") if overall_healthy else t("health.unhealthy")
    title = f"{t('health.title')} - {status_label}"

    # Get component status breakdown
    components_group_dict = {}
    if components and "aegis" in components:
        aegis_component = components["aegis"]
        if (
            hasattr(aegis_component, "sub_components")
            and aegis_component.sub_components
        ):
            components_group = aegis_component.sub_components.get("components")
            if (
                components_group
                and hasattr(components_group, "sub_components")
                and components_group.sub_components
            ):
                components_group_dict = components_group.sub_components

    component_counts = _count_status_types(components_group_dict)
    component_breakdown = _format_status_breakdown(component_counts)
    component_status_color = _get_status_color(component_counts)

    panel_content = [
        f"{t('health.overall_status')} [bold {overall_color}]"
        + status_label
        + f"[/bold {overall_color}]",
        f"{t('health.health_percentage')} [bold]"
        f"{health_percentage:.{CLI.HEALTH_PERCENTAGE_DECIMALS}f}%[/bold]",
        f"{t('health.components_label')} [bold {component_status_color}]"
        f"{component_breakdown}[/bold {component_status_color}]",
    ]

    # Add service information
    services_group_dict = {}
    if components and "aegis" in components:
        aegis_component = components["aegis"]
        if (
            hasattr(aegis_component, "sub_components")
            and aegis_component.sub_components
        ):
            services_group = aegis_component.sub_components.get("services")
            if (
                services_group
                and hasattr(services_group, "sub_components")
                and services_group.sub_components
            ):
                services_group_dict = services_group.sub_components

    if services_group_dict:
        service_counts = _count_status_types(services_group_dict)
        service_breakdown = _format_status_breakdown(service_counts)
        service_status_color = _get_status_color(service_counts)

        panel_content.append(
            f"{t('health.services_label')} [bold {service_status_color}]"
            f"{service_breakdown}[/bold {service_status_color}]"
        )

    panel_content.append(f"{t('health.timestamp_label')} {timestamp}")

    console.print(
        Panel("\n".join(panel_content), title=title, border_style=overall_color)
    )

    # Component and Service Tree Display
    tree_title = t("health.component_tree")
    if hasattr(health_data, "has_services") and health_data.has_services:
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
        if hasattr(component, "sub_components") and component.sub_components:
            _display_sub_components(component.sub_components, detailed, level=1)

        # Show metadata for main components if detailed and available
        elif detailed and component.metadata:
            # Special handling for scheduler component
            if name == "scheduler" and _is_scheduler_metadata(component.metadata):
                _display_scheduler_metadata(component.metadata, "", True, detailed)
            else:
                # Generic metadata display for other components
                metadata_str = json.dumps(component.metadata, separators=(",", ":"))
                max_length = CLI.MAX_METADATA_DISPLAY_LENGTH
                if len(metadata_str) > max_length:
                    metadata_str = metadata_str[: max_length - 3] + "..."
                console.print(f"    [dim]({metadata_str})[/dim]")

    # System information (only in detailed mode)
    if detailed and isinstance(health_data, DetailedHealthResponse):
        system_info = health_data.system_info
        if system_info:
            sys_info_content = []
            for key, value in system_info.items():
                label_key = f"health.sysinfo.{key}"
                label = t(label_key)
                if label == label_key:
                    label = key.replace("_", " ").title()
                sys_info_content.append(f"{label}：{value}")

            console.print(
                Panel(
                    "\n".join(sys_info_content),
                    title=t("health.system_info"),
                    border_style="dim",
                )
            )
