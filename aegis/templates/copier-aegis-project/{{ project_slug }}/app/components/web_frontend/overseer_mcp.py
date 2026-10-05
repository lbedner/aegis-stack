"""Overseer > MCP: what an outside assistant is served (and each granted
tool it is not, with why), how to connect one, and what each client did,
from ``ui_mcp``. Read-only: the grant is ``MCP_TOOLS``, and a client's
proposals are approved where every card is."""

from typing import Any

from app.services.system import ui_mcp
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest
from .rendering import columns, status_cell

SECTIONS = ((None, {"overview": "Overview", "activity": "Activity"}),)
# Badge tones: a proposal is the effect to look at, a failure the result.
EFFECT_TONES = {"read": "muted", "proposes": "warn"}
RESULT_TONES = {ui_mcp.OK: "ok", ui_mcp.FAILED: "error"}


def _badges(row: dict[str, str]) -> dict[str, Any]:
    """The row with its effect (and result, on a call) as status cells."""
    cells: dict[str, Any] = {"effect": status_cell(row["effect"], EFFECT_TONES[row["effect"]])}
    if "result" in row:
        cells["result"] = status_cell(row["result"], RESULT_TONES[row["result"]])
    return row | cells


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    if section == "activity":
        found = await ui_mcp.recorded()
        return {
            "section_subtitle": "What each client looked at and proposed, newest first.",
            "activity": found | {"calls": [_badges(c) for c in found["calls"]]},
            "client_columns": columns(ui_mcp.CLIENT_COLUMNS),
            "call_columns": columns(ui_mcp.CALL_COLUMNS, status=("effect", "result")),
        }
    grant = ui_mcp.grant()
    return {
        "section_subtitle": "What an outside assistant is served, and how it connects.",
        "served": [_badges(t) for t in grant["served"]],
        "dropped": grant["dropped"],
        "none_served": ui_mcp.NONE_SERVED,
        "served_columns": columns(ui_mcp.SERVED_COLUMNS, status=("effect",)),
        "dropped_columns": columns(ui_mcp.DROPPED_COLUMNS),
        "connect": ui_mcp.connect(),
    }
