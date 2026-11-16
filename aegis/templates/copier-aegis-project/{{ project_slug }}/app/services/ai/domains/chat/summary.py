"""A conversation's running summary: what fell out of the history window.

A turn replays as much history as its budget holds, cut a slab at a time
(``prompt._history_start``), and what was said only in the turns that fell
out was gone. Those turns fold, off the request path
(``fold_conversation_task``), into one running summary kept on the
conversation's metadata, and the history builder puts it ahead of the
turns still in view (``window``).

The summary moves only when the cut does: a cut that falls due waits for
the fold that takes its turns in, so the two change in the same turn and a
prompt cache keeps reusing what the turns between them sent. Where no
worker runs nothing folds, and the history cuts as it always did.
"""

from dataclasses import dataclass
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.cache import get_cache
from app.core.discovery import present
from app.core.log import logger
from app.models.conversation import Conversation as ConversationModel
from app.services.ai.models import Conversation

SUMMARY_KEY = "summary"
# Long enough for the names, numbers and decisions of a long thread; it
# rides every turn, so it is capped like any replayed history.
SUMMARY_CHARS = 2_000
# The agent row that writes it (``writer``): its prompt and model while one
# is active, else ``SUMMARY_PROMPT`` on the model in force.
SUMMARIZER = "summarizer"
ACTION = "chat:summary"
# Folds run on the worker; a stack without one never folds.
FOLDS = present("app.components.worker")
# A fold is queued once per cut, on any worker engine: every turn while it
# runs finds it due again. Past this, a fold that never landed is queued anew.
_CLAIM_SECONDS = 15 * 60
# ponytail: a due cut waits for its fold while the held history stays within
# this multiple of the budget; past it the cut goes ahead, and the summary
# catches up when the fold lands (one more change for a cache to miss).
_HOLD_FACTOR = 1.5

INTRO = "Earlier in this conversation, before the turns below (a running summary):"
SUMMARY_PROMPT = (
    "You keep the running summary of a long conversation between a user and "
    "their assistant. You are given the summary so far (it may be empty) and "
    "the turns that have just left the assistant's view. Return the new "
    "summary: everything still worth knowing from both, in plain sentences. "
    "Keep names, amounts, dates, decisions, promises and open questions "
    f"exactly. Drop small talk. Stay under {SUMMARY_CHARS} characters. "
    "Return only the summary."
)


def summary_of(conversation: Conversation) -> dict[str, Any]:
    """The summary so far: ``text``, and ``through``, how many of the oldest
    history lines (``history_lines``) it covers."""
    kept = conversation.metadata.get(SUMMARY_KEY) or {}
    return {"text": kept.get("text", ""), "through": int(kept.get("through", 0))}


@dataclass(frozen=True)
class Window:
    """Where a turn's history starts, what rides ahead of it, and how far a
    fold is due to reach (0: none due)."""

    start: int
    summary: str
    fold_to: int


def window(
    conversation: Conversation, lengths: list[int], start: int, budget: int
) -> Window:
    """The turn's window, given each history line's length and the cut the
    budget alone makes (``start``). A cut past what the summary covers is
    due a fold; until it lands the cut stays where the summary reaches. A
    cut short of it (the budget grew) moves up to it: the summary never
    rides beside the turns it tells. A thread the budget holds whole needs
    no summary. A stack whose worker does not fold (``FOLDS``) is never
    due one."""
    kept = summary_of(conversation)
    through = kept["through"]
    fold_to = start if FOLDS and start > through else 0
    if fold_to and sum(lengths[through:]) <= budget * _HOLD_FACTOR:
        start = through
    if start and kept["text"]:
        start = max(start, through)
    text = kept["text"] if start else ""
    return Window(start, f"{INTRO}\n{text}" if text else "", fold_to)


async def _condense(prompt: str, *, conversation: Conversation) -> str:
    """One model call: the folded summary, metered against the
    conversation's user."""
    from app.services.ai.domains.llm.writer import write

    # On a local server with one slot (llama-server ``-np 1``) this request
    # takes the slot's prompt cache from the chat, so the chat's next turn
    # reads its prompt afresh: once per cut, not per turn. The summarizer's
    # agent row can pin another model (or a server of its own) to spare it.
    text, _model = await write(
        SUMMARIZER,
        SUMMARY_PROMPT,
        str,
        prompt,
        action=ACTION,
        owner_user_id=conversation.metadata.get("user_id"),
    )
    return text.strip()[:SUMMARY_CHARS]


async def fold(conversation: Conversation, *, upto: int) -> bool:
    """Fold the history lines before ``upto`` into the conversation's
    summary. Safe to repeat: a fold already done costs nothing. True when
    the summary changed; the caller saves it."""
    from app.services.ai.service.prompt import history_lines

    so_far = summary_of(conversation)
    if upto <= so_far["through"]:
        return False
    fallen = "\n".join(history_lines(conversation.messages)[so_far["through"] : upto])
    prompt = (
        f"Summary so far:\n{so_far['text'] or '(none)'}\n\n"
        f"Turns that left view:\n{fallen}"
    )
    text = await _condense(prompt, conversation=conversation)
    conversation.metadata[SUMMARY_KEY] = {"text": text, "through": upto}
    return True


async def enqueue_fold(conversation_id: str, upto: int) -> None:
    """After a turn: hand the fold it found due (``window``: never on a
    stack that does not fold) to the worker, once per cut. Never fails the
    turn: a fold missed now is due again on the next."""
    try:
        if not await get_cache().claim(
            f"chat:fold:{conversation_id}:{upto}", ttl=_CLAIM_SECONDS
        ):
            return
        from app.components.worker import pools
        from app.core.constants import QueueName

        await pools.enqueue_task(
            "fold_conversation_task", QueueName.SYSTEM, conversation_id, upto
        )
    except Exception as exc:  # noqa: BLE001 - the turn goes on regardless
        logger.warning(f"Could not queue a conversation fold: {exc}")


def merged_summary(
    stored: dict[str, Any] | None, saving: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The summary a conversation's save keeps: a turn that read the
    conversation before a fold landed must not put back the older one."""
    if not stored or not saving:
        return saving or stored
    if int(stored.get("through", 0)) > int(saving.get("through", 0)):
        return stored
    return saving


async def write_summary(
    session: AsyncSession, conversation_id: str, folded: dict[str, Any]
) -> bool:
    """Write ONLY the summary into the stored metadata as it is now: a turn
    may have landed meanwhile, and saving a copy read earlier would undo
    what it changed. False when the conversation is gone."""
    row = await session.get(ConversationModel, conversation_id)
    if row is None:
        return False
    meta = row.meta_data or {}
    row.meta_data = {
        **meta,
        SUMMARY_KEY: merged_summary(meta.get(SUMMARY_KEY), folded),
    }
    session.add(row)
    return True


async def fold_conversation(conversation_id: str, upto: int) -> dict[str, Any] | None:
    """The worker's fold: read the conversation and condense it, holding no
    session; the summary for its job to write (``write_summary``), or None
    when nothing folded."""
    from app.services.ai.domains.chat.conversation import ConversationManager

    conversation = await ConversationManager().get_conversation(conversation_id)
    if conversation is None or not await fold(conversation, upto=upto):
        return None
    return conversation.metadata[SUMMARY_KEY]
