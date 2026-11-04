"""
Components command implementation.
"""

import typer

from ..constants import ComponentNames
from ..core.components import CORE_COMPONENTS, ComponentType
from ..core.menu import menu
from ..i18n import t


def _translated_desc(name: str, fallback: str) -> str:
    """Get translated description for a component, with fallback."""
    comp_key = f"component.{name}"
    result = t(comp_key)
    return result if result != comp_key else fallback


def components_command() -> None:
    """List available components and their dependencies."""

    typer.echo(f"\n{t('components.core_title')}")
    typer.echo("=" * 40)
    for component in CORE_COMPONENTS:
        if component == ComponentNames.BACKEND:
            typer.echo(t("components.backend_desc"))
        elif component == ComponentNames.FRONTEND:
            typer.echo(t("components.frontend_desc"))

    parts = menu()["components"]

    def _print_section(title_key: str, component_type: ComponentType) -> None:
        typer.echo(f"\n{t(title_key)}")
        typer.echo("=" * 40)
        for part in parts:
            if part["group"] != component_type.value:
                continue
            name = part["name"]
            desc = _translated_desc(name, part["description"])
            typer.echo(f"  {name:12} - {desc}")
            if part["requires"]:
                typer.echo(
                    f"               {t('components.requires', deps=', '.join(part['requires']))}"
                )
            if part["recommends"]:
                typer.echo(
                    f"               {t('components.recommends', deps=', '.join(part['recommends']))}"
                )

    _print_section("components.infra_title", ComponentType.INFRASTRUCTURE)
    _print_section("components.frontend_title", ComponentType.FRONTEND)

    typer.echo(f"\n{t('components.usage_hint')}")
