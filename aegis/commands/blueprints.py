"""
Blueprints command implementation.
"""

import typer

from ..blueprints import BLUEPRINTS
from ..cli import brand
from ..i18n import t


def _translated(key: str, fallback: str) -> str:
    """Translated blueprint copy, falling back to the registry string."""
    result = t(key)
    return result if result != key else fallback


def blueprints_command() -> None:
    """List available blueprints (preset component and service selections)."""
    typer.echo()
    brand.accent(t("blueprints.title"), bold=True)
    typer.echo("=" * 40)

    if not BLUEPRINTS:
        typer.echo(t("blueprints.none_available"))
        return

    for slug, bp in BLUEPRINTS.items():
        title = _translated(f"blueprint.{slug}.title", bp.title)
        desc = _translated(f"blueprint.{slug}.desc", bp.description)
        typer.echo()
        typer.echo(f"  {brand.accent_text(slug)}  {title}")
        typer.echo(f"      {desc}")
        typer.echo(
            f"      {brand.muted_text(t('blueprints.includes', names=', '.join(bp.contents)))}"
        )

    typer.echo()
    brand.muted(t("blueprints.usage_hint"))
    typer.echo(f"   {brand.accent_text('aegis init my-app --blueprint <name>')}")
