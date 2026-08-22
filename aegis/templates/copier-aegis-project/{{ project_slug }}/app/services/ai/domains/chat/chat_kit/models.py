"""Value types for the tool-calling chat kit.

GENERIC — nothing here knows about Pulse, metrics, or projects. The kit is a
reusable primitive (backports to aegis-stack): a caller supplies a persona,
context providers, tools, and a budget policy, and gets streaming
tool-calling chat with cost control and persistence-ready outputs.

Scope vs. deps, the two identity objects:

- ``ChatScope`` is what the KIT needs — who is asking (``user_id``) and which
  chat surface (``surface``, e.g. "metrics" / "support"). It drives budgeting
  and conversation scoping and is deliberately tiny.
- The agent's *deps* are whatever the caller's TOOLS and context providers
  need (a DB session, a subject id, an entitlements snapshot). The kit is
  generic over that type and never inspects it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatScope:
    """Who is asking and on which surface. All the kit needs to budget and
    scope a conversation; policy-specific identity lives in the agent deps."""

    user_id: str
    surface: str


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One prior turn, model-agnostic. Converted to the provider's native
    message-history format by the agent; the caller stores whatever it likes.

    ``timestamp`` is set only when loading a persisted turn (ISO-8601, UTC) —
    it feeds the UI's hover time and day dividers, and is ignored by the
    model-history conversion (the model doesn't need it)."""

    role: ChatRole
    content: str
    timestamp: str | None = None


# --- Stream frames -------------------------------------------------------
# One NDJSON object per line on the wire (see ``streaming.py``). A tagged
# union so the browser / CLI can switch on ``kind`` without positional
# guessing. Frames are the kit's only output contract.


@dataclass(frozen=True, slots=True)
class DeltaFrame:
    """An incremental chunk of the assistant's answer."""

    text: str
    kind: Literal["delta"] = "delta"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text}


@dataclass(frozen=True, slots=True)
class DoneFrame:
    """Terminal success frame: the full answer plus exact cost accounting.

    ``answer`` is the accumulated text so the caller can persist the
    assistant turn without re-joining deltas; ``usage`` / ``cost_usd`` come
    from the provider's own token counts through the shared ledger path.
    """

    answer: str
    usage: dict[str, int]
    cost_usd: float
    tool_calls: int = 0
    kind: Literal["done"] = "done"

    def to_dict(self) -> dict[str, Any]:
        # ``answer`` rides the wire too, so a non-streaming client can take the
        # final text straight from the done frame instead of re-joining deltas
        # (the field's stated purpose).
        return {
            "kind": self.kind,
            "answer": self.answer,
            "usage": self.usage,
            "cost_usd": self.cost_usd,
            "tool_calls": self.tool_calls,
        }


@dataclass(frozen=True, slots=True)
class BlockedFrame:
    """Terminal refusal frame emitted BEFORE any model call — the gate or the
    budget guard declined. ``reason`` is machine-readable ("budget",
    "entitlement"); ``message`` is the plain sentence shown in the thread."""

    reason: str
    message: str
    kind: Literal["blocked"] = "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason, "message": self.message}


@dataclass(frozen=True, slots=True)
class ErrorFrame:
    """Terminal failure frame: the model or a tool raised mid-turn. Partial
    text (if any) already reached the client as delta frames."""

    message: str
    kind: Literal["error"] = "error"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message}


StreamFrame = DeltaFrame | DoneFrame | BlockedFrame | ErrorFrame


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """The outcome of a per-user spend check for one action family."""

    allowed: bool
    spent_usd: float
    budget_usd: float
    window: str = "today"
    # Carried through so a fail-open (DB unreadable) can be logged/asserted
    # distinctly from a genuine under-budget allow.
    degraded: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.budget_usd - self.spent_usd)
