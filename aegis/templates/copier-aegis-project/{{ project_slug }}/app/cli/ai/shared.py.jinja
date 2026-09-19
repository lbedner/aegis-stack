"""The ``ai`` command group, and what every command in it needs.

The Typer instance lives here rather than in ``__init__`` so the
command modules can import it without importing the package that
imports them.
"""

import typer

from app.cli import theme
from app.i18n import lazy_t

from ...services.ai.models import (
    AIProvider,
    get_provider_capabilities,
)

app = typer.Typer(help=lazy_t("ai.help"))
console = theme.console()


PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "public": "LLM7.io",
    "unknown": "LLM7.io",
}


def _use_streaming(provider: AIProvider, requested: bool = True) -> bool:
    """Whether to stream responses for this provider.

    Follows the provider capabilities matrix: keyless endpoints
    (public/LLM7.io, pollinations) reject or fake ``stream=true``, so
    their responses render non-streaming.
    """
    return requested and get_provider_capabilities(provider).supports_streaming


def get_provider_display_name(provider: AIProvider | str) -> str:
    """Get display name for a provider, with aliases for branding."""
    value = provider.value if isinstance(provider, AIProvider) else provider
    return PROVIDER_DISPLAY_NAMES.get(value, value)
