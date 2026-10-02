"""Context for the Overseer AI page's sections.

Phase one of the Flet AI modal's port: whether the service is set up and
what it has done (Overview: the model in effect and where it comes from,
usage, configuration problems), and every provider with what it needs
(Providers, from the same ``provider_readiness`` the ``ai providers``
command prints). Read-only: keys live in ``.env`` until the Secrets work
gives them a home. Registered only in projects with the AI service (see
``overseer_sections``).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.components.backend.api.ai.service import ai_service
from app.core.config import settings
from app.core.formatting import format_relative_time
from app.services.ai.domains.llm.provider_management import (
    ProviderReadiness,
    provider_readiness,
)
from app.services.system.models import ComponentStatus

from .overseer_ai_common import (
    HAS_RAG,
    HAS_VOICE,
    PERSISTED,
    dollars,
    get_current_config,
    label,
    mark_urls,
    per_million,
    section_url,
)
from .overseer_nav import SectionRequest
from .rendering import chart, status_cell

SECTIONS = (
    (None, {"overview": "Overview", "chat": "Chat"}),
    *(
        (
            (
                "Activity",
                {"usage": "Usage", "costs": "Costs", "sentiment": "Sentiment"},
            ),
        )
        if PERSISTED
        else ()
    ),
    *((("Agents", {"agents": "Agents", "memory": "Memory"}),) if PERSISTED else ()),
    *(
        (("Knowledge", {"knowledge": "Knowledge", "search": "Search"}),)
        if HAS_RAG
        else ()
    ),
    *((("Voice", {"voice": "Voice"}),) if HAS_VOICE else ()),
    (
        "Configuration",
        ({"catalog": "Catalog"} if PERSISTED else {}) | {"providers": "Providers"},
    ),
)

# The usage window: a label, and how far back it reaches (None: all time).
WINDOWS = {
    "24h": ("24 hours", timedelta(hours=24)),
    "7d": ("7 days", timedelta(days=7)),
    "30d": ("30 days", timedelta(days=30)),
    "all": ("All time", None),
}
DEFAULT_WINDOW = "7d"
RECENT_CALLS = 25
SENTIMENTS = ("positive", "neutral", "negative")

ENGINES = {"pydantic-ai": "Pydantic AI", "langchain": "LangChain"}
STATUS = {
    "not_installed": ("Not installed", "muted"),
    "needs_key": ("Needs a key", "warn"),
    "ready": ("Ready", "ok"),
}


def _set_by(current: Any) -> str:
    if current.source == "override":
        return "A stored choice (llm use, or the dashboard)"
    return "AI_MODEL in .env"


async def _overview(ai: ComponentStatus) -> dict[str, Any]:
    meta = ai.metadata or {}
    current = await get_current_config()
    return {
        "figures": [
            {
                "label": "Conversations",
                "value": f"{meta.get('total_conversations', 0):,}",
            },
            {"label": "Messages", "value": f"{meta.get('total_messages', 0):,}"},
            {"label": "Tokens", "value": f"{meta.get('total_tokens', 0) or 0:,}"},
            {"label": "Cost", "value": dollars(meta.get("total_cost") or 0)},
        ],
        "model": [
            ("Provider", label(current.provider)),
            ("Model", current.model),
            ("Set by", _set_by(current)),
            (
                ".env default",
                current.env_model if current.source == "override" else None,
            ),
            ("In the catalog", "Yes" if current.in_catalog else "No"),
            (
                "Context window",
                f"{current.context_window:,} tokens"
                if current.context_window
                else None,
            ),
            ("Input price", per_million(current.input_price)),
            ("Output price", per_million(current.output_price)),
            ("Temperature", current.temperature),
            ("Max tokens", f"{current.max_tokens:,}"),
        ],
        "service": [
            ("Engine", ENGINES.get(meta.get("engine", ""), meta.get("engine"))),
            ("Enabled", "Yes" if meta.get("enabled") else "No"),
            ("Storage", meta.get("persistence") or meta.get("storage")),
            ("Users", meta.get("unique_users")),
        ],
        "problems": list(meta.get("validation_errors") or []),
    }


def _yes(flag: bool) -> str | None:
    return "Yes" if flag else None


async def _icons(db: Any, rows: list[ProviderReadiness]) -> dict[str, str]:
    """Each provider's logo URL. The org is named by the provider's key or
    its label (``LLM7.io``)."""
    return await mark_urls(
        db, {r.provider.value: (r.provider.value, r.label) for r in rows}
    )


def _provider_row(row: ProviderReadiness, icon_url: str | None) -> dict[str, Any]:
    label, tone = STATUS[row.status]
    if row.current:
        label, tone = (
            ("Current", "ok")
            if row.status == "ready"
            else (
                f"Current: {label.lower()}",
                "error",
            )
        )
    caps = row.capabilities
    return {
        "name": row.label,
        "icon_url": icon_url,
        "status": status_cell(label, tone),
        "key": row.env_var or "Not needed",
        "key_set": None if row.keyless else ("Yes" if row.has_key else "No"),
        "free": _yes(caps.free_tier_available),
        "streaming": _yes(caps.supports_streaming),
        "tools": _yes(caps.supports_function_calling),
        "vision": _yes(caps.supports_vision),
        "get_key": {"label": "Get a key", "url": row.key_url} if row.key_url else None,
    }


async def usage_stats(**window: Any) -> dict[str, Any]:
    """The usage ledger's totals (a persistence backend's service method)."""
    return await ai_service.get_usage_stats(**window)


def _call(r: dict[str, Any], icon_url: str | None) -> dict[str, Any]:
    ms = r.get("duration_ms")
    return {
        "when": format_relative_time(r.get("timestamp")),
        "model": r.get("model"),
        "icon_url": icon_url,
        "action": r.get("action"),
        "tokens": f"{r.get('input_tokens', 0):,} / {r.get('output_tokens', 0):,}",
        "outcome": status_cell("Ok", "ok")
        if r.get("success", True)
        else status_cell("Failed", "error"),
        "detail": [
            ("Error", r.get("error_message")),
            ("Duration", f"{ms / 1000:.1f}s" if ms is not None else None),
            ("Tool calls", r.get("tool_calls")),
            ("Cache read", r.get("cache_read_tokens")),
            ("Cache write", r.get("cache_write_tokens")),
            ("User", r.get("user_id")),
            ("At", r.get("timestamp")),
        ],
    }


async def _usage(db: Any, query: dict[str, str]) -> dict[str, Any]:
    window = query.get("window") if query.get("window") in WINDOWS else DEFAULT_WINDOW
    reach = WINDOWS[window][1]
    stats = await usage_stats(
        start_time=datetime.now(UTC) - reach if reach else None,
        recent_limit=RECENT_CALLS,
    )
    # Each model's vendor, from the breakdown; the recent calls fall in the
    # same window, so it places them too. One lookup for both tables.
    vendor_of = {m["model_id"]: m.get("vendor") for m in stats.get("models", [])}
    marks = await mark_urls(db, {v: (v,) for v in set(vendor_of.values()) if v})
    icon_of = {model: marks.get(vendor or "") for model, vendor in vendor_of.items()}
    return {
        "chips": [
            {
                "label": label,
                "url": section_url("usage", window=key),
                "active": key == window,
            }
            for key, (label, _) in WINDOWS.items()
        ],
        "figures": [
            {"label": "Requests", "value": f"{stats.get('total_requests', 0):,}"},
            {
                "label": "Tokens",
                "value": f"{stats.get('total_tokens', 0):,}",
                "caption": f"{stats.get('input_tokens', 0):,} in, "
                f"{stats.get('output_tokens', 0):,} out",
            },
            {"label": "Success rate", "value": f"{stats.get('success_rate', 100.0)}%"},
        ],
        "models": [
            {
                "model": m.get("model_title") or m.get("model_id"),
                "icon_url": icon_of.get(m.get("model_id")),
                "vendor": label(m.get("vendor") or ""),
                "requests": m.get("requests", 0),
                "tokens": m.get("tokens", 0),
                "share": f"{m.get('percentage', 0)}%",
            }
            for m in stats.get("models", [])
        ],
        "recent": [
            _call(r, icon_of.get(r.get("model")))
            for r in stats.get("recent_activity", [])
        ],
    }


async def sentiment_stats() -> dict[str, Any]:
    """The sentiment job's tallies (a persistence backend's module)."""
    from app.services.ai.domains.chat.sentiment import sentiment_stats as stats

    return await stats()


async def _sentiment() -> dict[str, Any]:
    stats = await sentiment_stats()
    spread = stats.get("distribution") or {}
    return {
        "enabled": stats.get("enabled", False),
        "total": stats.get("total", 0),
        "figures": [
            {"label": "Scored", "value": f"{stats.get('total', 0):,}"},
            {"label": "Average score", "value": stats.get("average_score", 0.0)},
            {
                "label": "Negative",
                "value": spread.get("negative", 0),
                "tone": "error" if spread.get("negative") else None,
            },
        ],
        "chart": chart(
            [s.title() for s in SENTIMENTS],
            "Conversations",
            [spread.get(s, 0) for s in SENTIMENTS],
        ),
        "negatives": [
            {
                "summary": n.get("summary"),
                "when": format_relative_time(n.get("created_at")),
            }
            for n in stats.get("recent_negatives", [])
        ],
    }


async def section_context(
    section: str, ai: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    if section == "overview":
        return await _overview(ai)
    if section == "usage":
        return await _usage(req.db, dict(req.query))
    if section == "sentiment":
        return await _sentiment()
    if section == "costs":
        from . import overseer_ai_costs

        return await overseer_ai_costs.section_context(req.db, req.query)
    if section == "agents":
        from . import overseer_ai_agents

        return await overseer_ai_agents.agents_context(req.db, req.query)
    if section == "memory":
        from . import overseer_ai_agents

        return await overseer_ai_agents.memory_context(req.db, req.query)
    if section in ("knowledge", "search"):
        from . import overseer_ai_rag

        if section == "knowledge":
            return await overseer_ai_rag.knowledge_context(req.query)
        return await overseer_ai_rag.search_context()
    if section == "chat":
        from . import overseer_ai_chat

        return await overseer_ai_chat.surface_context()
    if section == "voice":
        from . import overseer_ai_voice

        return await overseer_ai_voice.voice_context()
    if section == "catalog":
        from . import overseer_ai_catalog

        return await overseer_ai_catalog.section_context(req.db, req.query)
    rows = await provider_readiness(settings)
    icons = await _icons(req.db, rows)
    return {"rows": [_provider_row(r, icons.get(r.provider.value)) for r in rows]}
