"""
Typer callback functions for CLI options.

This module contains callback functions used to validate and process
CLI options before command execution.
"""

from collections.abc import Callable

import typer

from ..constants import ComponentNames, Messages, WorkerBackends
from ..core.ai_service_parser import parse_ai_service_config
from ..core.auth_service_parser import parse_auth_service_config
from ..core.component_utils import (
    clean_component_names,
    extract_base_component_name,
    extract_base_service_name,
    extract_engine_info,
    restore_engine_info,
)
from ..core.dependency_resolver import DependencyResolver
from ..core.insights_service_parser import parse_insights_service_config
from ..core.option_spec import is_spec_with_options
from ..core.service_resolver import ServiceResolver
from ..core.services import SERVICES
from ..i18n import t
from . import brand
from .interactive import set_ai_service_config, set_auth_level_selection
from .utils import expand_scheduler_dependencies


def validate_and_resolve_components(
    ctx: typer.Context, param: typer.CallbackParam, value: str | None
) -> list[str] | None:
    """Validate and resolve component dependencies."""
    if not value:
        return None

    # Skip validation during help generation, but not for tests
    # Mock objects don't have a real resilient_parsing attribute set to True
    if hasattr(ctx, "resilient_parsing") and ctx.resilient_parsing is True:
        return None

    # Parse comma-separated string
    components_raw = [c.strip() for c in value.split(",")]

    # Check for empty components before filtering
    if any(not c for c in components_raw):
        brand.error(Messages.EMPTY_COMPONENT_NAME, err=True)
        raise typer.Exit(1)

    selected = [c for c in components_raw if c]

    # Expand scheduler[backend] dependencies first
    selected = expand_scheduler_dependencies(selected)

    # Validate worker backend options
    for component in selected:
        base_name = extract_base_component_name(component)
        if base_name == ComponentNames.WORKER:
            backend = extract_engine_info(component)
            if backend and backend not in WorkerBackends.ALL:
                brand.error(
                    f"Invalid worker backend '{backend}'. "
                    f"Available: {', '.join(WorkerBackends.ALL)}",
                    err=True,
                )
                raise typer.Exit(1)

    # Validate components exist (use clean names for validation)
    clean_selected = clean_component_names(selected)
    errors = DependencyResolver.validate_components(clean_selected)
    if errors:
        for error in errors:
            brand.error(error, err=True)
        raise typer.Exit(1)

    # Resolve dependencies (using clean names)
    resolved_clean = DependencyResolver.resolve_dependencies(clean_selected)

    # Restore engine info to resolved components
    resolved = restore_engine_info(resolved_clean, selected)

    # Show dependency resolution (use clean names for dependency calculation)
    original_clean = clean_component_names(selected)
    auto_added = DependencyResolver.get_missing_dependencies(original_clean)
    if auto_added:
        typer.echo(f"Auto-added dependencies: {', '.join(auto_added)}")

    # Show recommendations
    recommendations = DependencyResolver.get_recommendations(resolved_clean)
    if recommendations:
        rec_list = ", ".join(recommendations)
        typer.echo(f"Recommended: {rec_list}")
        # Note: Skip interactive recommendations for now to keep it simple

    return resolved


def _split_service_list(value: str) -> list[str]:
    """
    Split comma-separated service list respecting bracket syntax.

    Handles ai[langchain, openai] where commas inside brackets are preserved.

    Args:
        value: Comma-separated service string like "ai[langchain, openai], auth"

    Returns:
        List of service strings with brackets preserved
    """
    services = []
    current = ""
    bracket_depth = 0

    for char in value:
        if char == "[":
            bracket_depth += 1
            current += char
        elif char == "]":
            # Only decrement if we're inside brackets to prevent negative depth
            # from mismatched brackets like "ai],auth"
            if bracket_depth > 0:
                bracket_depth -= 1
            current += char
        elif char == "," and bracket_depth == 0:
            # Only split on comma if we're not inside brackets
            if current.strip():
                services.append(current.strip())
            current = ""
        else:
            current += char

    # Don't forget the last service
    if current.strip():
        services.append(current.strip())

    return services


def _handle_ai_options(service: str) -> None:
    """Parse ``ai[...]`` options, store config, echo the selection."""
    ai_config = parse_ai_service_config(service)
    set_ai_service_config(
        service_name="ai",
        framework=ai_config.framework,
        backend=ai_config.backend,
        providers=ai_config.providers,
    )
    typer.echo(
        f"AI service: framework={ai_config.framework}, "
        f"backend={ai_config.backend}, "
        f"providers={','.join(ai_config.providers)}"
    )


def _handle_auth_options(service: str) -> None:
    """Parse ``auth[...]`` options, store level/engine, echo the selection."""
    auth_config = parse_auth_service_config(service)
    set_auth_level_selection(service_name="auth", level=auth_config.level)
    if auth_config.engine:
        from .interactive import set_database_engine_selection

        set_database_engine_selection(auth_config.engine)
    typer.echo(f"Auth service: level={auth_config.level}")


def _handle_insights_options(service: str) -> None:
    """Parse ``insights[...]`` options (validation + echo; no stored state)."""
    insights_config = parse_insights_service_config(service)
    typer.echo(f"Insights service: sources={','.join(insights_config.sources)}")


# Bracket-syntax handlers, keyed by base service name. Each entry is
# (display label for error messages, handler). A handler parses the
# service's options, stores any interactive-state config, and echoes the
# selection; a ValueError surfaces as "Invalid <label> service syntax".
# Services without an entry accept no bracket handling here (the generic
# parse in ServiceResolver still validates their options).
_SERVICE_OPTION_HANDLERS: dict[str, tuple[str, Callable[[str], None]]] = {
    "ai": ("AI", _handle_ai_options),
    "auth": ("auth", _handle_auth_options),
    "insights": ("insights", _handle_insights_options),
}


def apply_service_option_handlers(selected_services: list[str]) -> None:
    """Run the bracket-syntax handler for every service that has one.

    Shared by the ``--services`` callback and the ``--blueprint`` expansion
    so both paths store service config (AI provider/framework, auth level,
    ...) identically.
    """
    for service in selected_services:
        entry = _SERVICE_OPTION_HANDLERS.get(extract_base_service_name(service))
        if entry is None or not is_spec_with_options(service):
            continue
        label, handler = entry
        try:
            handler(service)
        except ValueError as e:
            brand.error(f"Invalid {label} service syntax: {e}", err=True)
            raise typer.Exit(1) from None


def validate_and_resolve_services(
    ctx: typer.Context, param: typer.CallbackParam, value: str | None
) -> list[str] | None:
    """Validate and resolve service dependencies to components."""
    if not value:
        return None

    # Skip validation during help generation, but not for tests
    # Mock objects don't have a real resilient_parsing attribute set to True
    if hasattr(ctx, "resilient_parsing") and ctx.resilient_parsing is True:
        return None

    # Parse comma-separated string, respecting bracket syntax
    services_raw = _split_service_list(value)

    # Check for empty services before filtering
    if any(not s for s in services_raw):
        brand.error(Messages.EMPTY_SERVICE_NAME, err=True)
        raise typer.Exit(1)

    selected_services = [s for s in services_raw if s]

    # Validate services exist (extract base name to support bracket syntax like ai[langchain, openai])
    unknown_services = [
        s for s in selected_services if extract_base_service_name(s) not in SERVICES
    ]
    if unknown_services:
        brand.error(
            t("validation.unknown_services", names=", ".join(unknown_services)),
            err=True,
        )
        available = list(SERVICES.keys())
        typer.echo(f"Available services: {', '.join(available)}", err=True)
        raise typer.Exit(1)

    # Parse bracket-syntax options and store config, one handler per service
    # (see _SERVICE_OPTION_HANDLERS above). Handlers run in user-typed order.
    apply_service_option_handlers(selected_services)

    # Resolve services to components
    resolved_components, service_added = ServiceResolver.resolve_service_dependencies(
        selected_services
    )

    # Show what components were added by services
    if service_added:
        typer.echo(t("init.services_require", components=", ".join(service_added)))

    return selected_services
