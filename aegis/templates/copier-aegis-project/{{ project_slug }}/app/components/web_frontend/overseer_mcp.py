"""Overseer > MCP: what an outside assistant is served (and each granted
tool it is not, with why), how to connect one, what each client did, and
(with auth) the viewer's tokens, from ``ui_mcp``. The grant is
``MCP_TOOLS``, and a client's proposals are approved where every card is;
tokens are made and revoked through ``routes/partials/overseer_mcp``."""

from typing import Any

from app.services.system import ui_mcp
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest
from .rendering import columns, status_cell

# Tokens belong to people, so only with auth.
SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            "activity": "Activity",
            **({"tokens": "Tokens"} if ui_mcp.has_tokens() else {}),
        },
    ),
)
# Where this page's dialogs live (``routes/partials/overseer_mcp``).
PARTIALS = "/partials/overseer/mcp"
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
    if section == "tokens":
        return await _tokens(req)
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


async def _tokens(req: SectionRequest) -> dict[str, Any]:
    """The viewer's tokens (offered only with auth, so ``tokens`` is there)."""
    from app.components.mcp import tokens

    rows = await tokens.live(req.db, req.viewer.id)
    return {
        "section_subtitle": "What a client beyond stdio signs in with. Each reaches what its scope allows.",
        "tokens": [ui_mcp.token_row(row.model_dump()) for row in rows],
        "token_columns": columns(ui_mcp.TOKEN_COLUMNS),
        "no_tokens": ui_mcp.NO_TOKENS,
        "partials": PARTIALS,
    }
