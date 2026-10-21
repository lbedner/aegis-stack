"""
Services command implementation.
"""

import typer

from ..cli import brand
from ..core.services import SERVICE_GROUPS, group_header_key, services_in
from ..i18n import t


def _translated_service_desc(name: str, fallback: str) -> str:
    """Get translated description for a service, with fallback."""
    svc_key = f"service.{name}"
    result = t(svc_key)
    return result if result != svc_key else fallback


def services_command() -> None:
    """List available services and their dependencies."""

    typer.echo(f"\n{t('services.title')}")
    typer.echo("=" * 40)

    # Grouped by each service's category (``PluginSpec.category``), in
    # ``SERVICE_GROUPS`` order.
    services_found = False
    for category in SERVICE_GROUPS:
        type_services = services_in(category)
        if type_services:
            services_found = True
            header = t(group_header_key(category))
            typer.echo(f"\n{header}")
            typer.echo("-" * 40)

            for name, spec in type_services.items():
                desc = _translated_service_desc(name, spec.description)
                badge = f" {brand.experimental_badge()}" if spec.experimental else ""
                typer.echo(f"  {name:12} - {desc}{badge}")
                if spec.required_components:
                    typer.echo(
                        f"               {t('services.requires_components', deps=', '.join(spec.required_components))}"
                    )
                if spec.recommended_components:
                    typer.echo(
                        f"               {t('services.recommends_components', deps=', '.join(spec.recommended_components))}"
                    )
                if spec.required_services:
                    typer.echo(
                        f"               {t('services.requires_services', deps=', '.join(spec.required_services))}"
                    )

    if not services_found:
        typer.echo(t("services.none_available"))

    typer.echo(f"\n{t('services.usage_hint')}")
