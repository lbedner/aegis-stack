"""Per-turn context providers — the CLI-chat context pattern, generalized.

GENERIC. The template's chat rebuilds fresh context objects every message
(``HealthContext`` etc., each with a ``format_for_prompt``) and composes them
into the prompt. This turns that into a small protocol so any caller can push
"what's true right now" to the model without a tool call.

Providers run BEFORE the model call, so they receive the agent *deps*
directly (not a ``RunContext``). Each returns a formatted block or ``None``
when it has nothing to add. The agent appends the non-empty blocks to the
run's INSTRUCTIONS (the system block), after the frozen persona — not into
the user message. Two reasons, both prompt-cache economics:

- Context like a briefing is stable across turns (byte-identical until the
  underlying data changes), so persona + context form a stable system prefix
  that a provider-side cache breakpoint can serve at ~0.1x. Riding in the
  latest user message, the same bytes are re-billed at full price every turn.
- The replayed history then contains the user's PLAIN messages, matching
  what the model actually saw — so the growing message prefix stays
  append-only and cacheable too.

Division of labor with tools: providers answer "what's true now" (pushed
every turn, kept compact); tools answer "what happened / fetch history"
(pulled only when the question needs it).
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

from app.core.log import logger

# ``TypeVar`` + ``Generic`` rather than PEP 695 ``class Foo[DepsT]`` so the
# generated project imports on Python 3.11 (the template's floor). Deps flow
# only INTO providers (never out), so the parameter is contravariant.
DepsT = TypeVar("DepsT", contravariant=True)


@runtime_checkable
class ContextProvider(Protocol[DepsT]):
    """Builds one labeled context block from the agent deps, per turn."""

    name: str

    async def build(self, deps: DepsT) -> str | None: ...


class StaticContextProvider(Generic[DepsT]):
    """A provider that always emits the same text. Useful as a stub/demo and
    for genuinely fixed context (a date-format note, a capability blurb)."""

    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self._text = text

    async def build(self, deps: DepsT) -> str | None:
        return self._text or None


async def gather_context(
    providers: tuple[ContextProvider[DepsT], ...], deps: DepsT
) -> list[tuple[str, str]]:
    """Run every provider, returning ``(name, block)`` for the non-empty ones.

    A provider that raises is skipped with a warning — stale context must
    never fail a chat turn (same fail-open stance as the usage ledger).
    """
    blocks: list[tuple[str, str]] = []
    for provider in providers:
        try:
            block = await provider.build(deps)
        except Exception as exc:  # noqa: BLE001 - provider isolation is the point
            logger.warning(
                "chat context provider failed", provider=provider.name, error=str(exc)
            )
            continue
        if block:
            blocks.append((provider.name, block))
    return blocks


def compose_context(blocks: list[tuple[str, str]]) -> str | None:
    """Wrap context blocks as clearly-marked reference data for the run's
    instructions. The tags tell the model this is data to read, not
    instructions to follow — the persona prompt reinforces that. ``None``
    when there is nothing to add (the run then carries no extra block)."""
    if not blocks:
        return None
    return "\n\n".join(
        f'<context name="{name}">\n{content}\n</context>' for name, content in blocks
    )
