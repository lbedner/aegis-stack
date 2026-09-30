"""What the Overseer AI page's section modules share: where the page lives,
whether the AI service has a persistence backend, the model in effect,
and how a provider's name and a price read. ``overseer_ai`` (Overview,
Usage, Sentiment, Providers), ``overseer_ai_catalog`` and
``overseer_ai_agents`` import it at the top.
"""

from importlib.util import find_spec
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from app.core.config import settings
from app.services.ai.models import AIProvider
from app.services.ai.models.provider_names import provider_label

from .overseer_nav import page_url
from .rendering import with_query

# Usage, sentiment, the catalog and the registries read the AI service's
# tables, which exist only with a persistence backend (``ai[sqlite]`` /
# ``ai[postgres]``); on the memory backend none of those sections is offered.
PERSISTED = find_spec("app.services.ai.domains.chat.sentiment") is not None
# RAG is file-based (Chroma), so it needs no database: offered wherever
# ``ai[...,rag]`` installed it.
HAS_RAG = find_spec("app.services.rag") is not None
# Voice rides the ``ai[...,voice]`` option.
HAS_VOICE = find_spec("app.services.ai.domains.voice") is not None

PAGE = page_url("services", "ai")
PARTIALS = "/partials/overseer/ai"


def section_url(section: str, **query: str | list[str] | None) -> str:
    """One of the AI page's sections, its filters in the query string."""
    return with_query(f"{PAGE}/{section}", **query)


async def get_current_config() -> Any:
    """The model in effect. With a persistence backend that is the catalog
    service's answer (a stored choice can shadow ``.env``); on the memory
    backend there is no catalog and ``.env`` is the whole story."""
    if PERSISTED:
        from app.services.ai.domains.llm.llm_service import (
            get_current_config as current,
        )

        return await current()
    return SimpleNamespace(
        provider=settings.AI_PROVIDER,
        model=settings.AI_MODEL,
        temperature=settings.AI_TEMPERATURE,
        max_tokens=settings.AI_MAX_TOKENS,
        in_catalog=False,
        source="env",
        env_model=settings.AI_MODEL,
        context_window=None,
        input_price=None,
        output_price=None,
    )


def label(provider: str) -> str:
    """A provider or vendor as it reads to a person (``OpenAI``); a vendor
    that is not a provider reads as its name."""
    try:
        return provider_label(AIProvider(provider))
    except ValueError:
        return provider


def dollars(amount: float | None) -> str | None:
    """``$1,234.50``; None stays None (a total passes ``or 0``)."""
    return f"${amount:,.2f}" if amount is not None else None


def per_million(price: float | None) -> str | None:
    """A per-token price as people quote it: per million tokens."""
    return f"{dollars(price)} / 1M tokens" if price is not None else None


def icon_url(org: str) -> str:
    """Where the AI page's icon route serves ``org``'s mark (a slug or a
    name, as the catalog holds it)."""
    return f"{PARTIALS}/icons/{quote(org, safe='')}"


async def mark_urls(db: Any, names: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """``{key: logo URL}`` where the catalog holds a mark for one of the
    key's names (an org's slug or its name), served by the AI page's icon
    route. The Providers page, Usage and the chat's footers all read their
    logos through this; only a persistence backend has the catalog."""
    if not PERSISTED or not names:
        return {}
    from app.services.ai.domains.llm.queries import org_icons

    stored = await org_icons(db, [n for pair in names.values() for n in pair])
    found = {
        key: next((n for n in pair if n in stored), None) for key, pair in names.items()
    }
    return {key: icon_url(n) for key, n in found.items() if n}
