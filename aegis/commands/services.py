"""
Services command implementation.
"""

import typer

from ..cli import brand
from ..core.menu import menu
from ..core.services import SERVICE_GROUPS, group_header_key
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
    parts = menu()["services"]
    services_found = False
    for category in SERVICE_GROUPS:
        type_services = [p for p in parts if p["group"] == category.value]
        if type_services:
            services_found = True
            header = t(group_header_key(category))
            typer.echo(f"\n{header}")
            typer.echo("-" * 40)

            for part in type_services:
                name = part["name"]
                desc = _translated_service_desc(name, part["description"])
                badge = f" {brand.experimental_badge()}" if part["experimental"] else ""
                typer.echo(f"  {name:12} - {desc}{badge}")
                if part["requires"]:
                    typer.echo(
                        f"               {t('services.requires_components', deps=', '.join(part['requires']))}"
                    )
                if part["recommends"]:
                    typer.echo(
                        f"               {t('services.recommends_components', deps=', '.join(part['recommends']))}"
                    )
                if part["requires_services"]:
                    typer.echo(
                        f"               {t('services.requires_services', deps=', '.join(part['requires_services']))}"
                    )

    if not services_found:
        typer.echo(t("services.none_available"))

    typer.echo(f"\n{t('services.usage_hint')}")
