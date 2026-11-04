"""
Typer callback functions for CLI options.

This module contains callback functions used to validate and process
CLI options before command execution.
"""

import functools
from collections.abc import Callable
from typing import Any

import typer

from ..core.ai_service_parser import parse_ai_service_config
from ..core.auth_service_parser import parse_auth_service_config
from ..core.component_utils import (
    clean_component_names,
    extract_base_service_name,
    split_bracket_list,
)
from ..core.components import CORE_COMPONENTS
from ..core.dependency_resolver import DependencyResolver
from ..core.insights_service_parser import parse_insights_service_config
from ..core.option_spec import is_spec_with_options
from ..core.selection import SelectionError, check_components, check_services
from ..core.service_resolver import ServiceResolver
from ..i18n import t
from . import brand
from .interactive import set_ai_service_config, set_auth_level_selection


def _refuse_invalid_input(
    callback: Callable[..., list[str] | None],
) -> Callable[..., list[str] | None]:
    """Turn a refused selection into its rules, one error line each, and
    exit 1 rather than a traceback (``redis[``, ``payment[paypal]``)."""

    @functools.wraps(callback)
    def refuse(*args: Any, **kwargs: Any) -> list[str] | None:
        try:
            return callback(*args, **kwargs)
        except SelectionError as e:
            for rule in e.rules:
                brand.error(rule, err=True)
            raise typer.Exit(1) from None

    return refuse


@_refuse_invalid_input
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

    resolved = check_components(value)
    selected = split_bracket_list(value)

    added = [c for c in resolved if c not in selected and c not in CORE_COMPONENTS]
    if added:
        typer.echo(f"Auto-added dependencies: {', '.join(added)}")

    # Show recommendations
    recommendations = DependencyResolver.get_recommendations(
        clean_component_names(resolved)
    )
    if recommendations:
        typer.echo(f"Recommended: {', '.join(recommendations)}")

    return resolved


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


@_refuse_invalid_input
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

    selected_services = check_services(value)

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
