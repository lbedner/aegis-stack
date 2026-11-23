"""Context for the Overseer Inference page: every engine on its Overview
(``app.components.inference.overview``: a row each, the memory they report
in one bar, who runs on each, how to add one the app lacks), the nav
grouped by job, and a page per engine with its own tabs: the text engine's
(``overseer_inference_text``) and the speech server's
(``overseer_inference_speech``). Container and Logs follow, as on every page
with containers behind it.

A new engine is an ``overview.Engine`` with its row, and a page here.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, NamedTuple

from app.components.inference import overview
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus

from . import overseer_inference_speech as speech
from . import overseer_inference_text as text
from .overseer_nav import SectionRequest, page_url, tab_links
from .rendering import status_cell

OVERVIEW = "overview"
ENGINE_TEMPLATE = "pages/overseer/inference/_engine.html"


class EnginePage(NamedTuple):
    """An engine's page: the engine (its section, name and job), the stem
    of its tabs' templates, its tabs, and what each tab's template needs."""

    engine: overview.Engine
    templates: str
    tabs: Mapping[str, str]
    context: Callable[[str, SectionRequest], Awaitable[dict[str, Any]]]


ENGINES = (
    EnginePage(overview.text_engine(), "text", text.TABS, text.context),
    EnginePage(overview.SPEECH_ENGINE, "speech", speech.TABS, speech.context),
)
_BY_ID = {e.engine.id: e for e in ENGINES}


def _url(engine: str) -> str:
    return page_url("components", ComponentName.INFERENCE, engine)


def _sections() -> tuple[tuple[str | None, dict[str, str]], ...]:
    """The Overview, then each engine under its job."""
    jobs: dict[str, dict[str, str]] = {}
    for page in ENGINES:
        jobs.setdefault(page.engine.job, {})[page.engine.id] = page.engine.name
    return ((None, {OVERVIEW: "Overview"}), *jobs.items())


SECTIONS = _sections()


def _row(row: overview.EngineRow) -> dict[str, Any]:
    """An engine as the Overview's table shows it, linked to its page."""
    url = _url(row.id) if row.id in _BY_ID else None
    tone = "ok" if row.available else "error"
    return {
        "engine": {"label": row.name, "url": url},
        "job": row.job,
        "state": status_cell(overview.STATES[row.available], tone),
        "loaded": overview.holds_said(row),
        "memory": overview.memory_said(row),
        "used_by": overview.used_by_said(row),
    }


def _memory(found: overview.InferenceOverview) -> list[dict[str, Any]]:
    """Each engine's share of the memory they report together."""
    total = found.reported_bytes
    return [
        {
            "label": row.name,
            "value": overview.memory_said(row),
            "ratio": (row.memory_bytes or 0) / total if total else 0,
            "dot": dot,
        }
        for dot, row in enumerate(found.engines, start=1)
    ]


async def _overview(req: SectionRequest) -> dict[str, Any]:
    found = await overview.read_overview(req.db)
    return {
        "engines": [_row(r) for r in found.engines],
        "memory": _memory(found),
        "reported": overview.total_said(found),
        "reported_label": overview.REPORTED,
        "to_add": found.to_add,
    }


async def _engine(page: EnginePage, req: SectionRequest) -> dict[str, Any]:
    """An engine's page: the tab asked for (its Overview, else), its tab
    row, and the template that shows it."""
    tab = req.query.get("tab", OVERVIEW)
    tab = tab if tab in page.tabs else OVERVIEW
    return await page.context(tab, req) | {
        "tabs": tab_links(_url(page.engine.id), page.tabs, tab, OVERVIEW),
        "section_partial": ENGINE_TEMPLATE,
        "tab_partial": f"pages/overseer/inference/_{page.templates}_{tab}.html",
    }


async def section_context(
    section: str, inference: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """What the named section's template needs."""
    if page := _BY_ID.get(section):
        return await _engine(page, req)
    return await _overview(req)
