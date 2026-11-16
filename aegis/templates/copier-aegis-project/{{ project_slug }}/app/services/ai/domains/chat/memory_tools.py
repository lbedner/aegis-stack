"""The built-in memory tools: ``save_memory``, ``replace_memory``,
``update_memory`` and ``forget_memory`` let the model ask to keep, rewrite
or drop durable facts about a user mid-conversation. Each files an approval
card (``memory_changes``), and nothing changes until the user approves it;
the store itself is ``user_memory``.

User identity reaches the tool through ``current_user_id`` (a
ContextVar): the chat runtime sets it for the duration of a turn, and
the tool reads it when the model calls ``save_memory``. Without it the
tool declines politely instead of guessing.
"""

from typing import Any

from pydantic import BaseModel

from app.core.db import get_async_session
from app.core.log import logger
from app.core.tools import register_tool
from app.services.ai.domains.chat.user_memory import (
    MEMORY_CATEGORIES,
    current_user_id,
    saved_fact,
)

# The memory tools. Each files a card on the change queue (``memory_changes``):
# untrusted text reaches the assistant (a document, a fetched page), and a
# fact kept on its say-so is a standing instruction in every later prompt,
# as one dropped on its say-so is a standing instruction gone.
NO_USER = "No user context available; nothing was filed."


def _user(tool: str) -> str | None:
    """The turn's user, or None when the runtime bound none (``memory_user``):
    then the tool files nothing, and says so."""
    user_id = current_user_id.get()
    if not user_id:
        logger.warning(f"{tool} called without user context; nothing filed")
    return user_id or None


async def _propose(change_type: str, payload: dict[str, Any]) -> BaseModel:
    """File the card (``change_queue.tools.propose``): attributed to the
    turn's agent and conversation, owned by its owner, for the turn's user
    (``memory_changes`` takes whose memory from the turn, never a payload)."""
    from app.services.change_queue import tools as queue_tools

    return await queue_tools.propose(change_type, payload)


async def save_memory(new_fact: str, category: str = "general") -> BaseModel | str:
    """Ask the user to approve remembering one durable fact about them.

    Category is one of: {categories}. This files an approval card: nothing
    is remembered until the user approves it, so never say it is saved.
    """
    if _user("save_memory") is None:
        return NO_USER
    if not new_fact.strip():
        return "Nothing to save; provide a fact."
    return await _propose("memory.save", {"fact": new_fact, "category": category})


save_memory.__doc__ = (save_memory.__doc__ or "").format(
    categories=", ".join(MEMORY_CATEGORIES)
)


async def replace_memory(memory_text: str) -> BaseModel | str:
    """Ask the user to approve replacing everything known about them, one
    fact per line. Files an approval card: nothing changes until the user
    approves it."""
    if _user("replace_memory") is None:
        return NO_USER
    return await _propose("memory.replace", {"memory_text": memory_text})


async def update_memory(old_fact: str, new_fact: str) -> BaseModel | str:
    """Ask the user to approve rewriting one saved fact that has changed, in
    place, instead of saving a second one beside it. ``old_fact`` is a quote
    of the saved fact. Files an approval card: nothing changes until the
    user approves it."""
    if (user_id := _user("update_memory")) is None:
        return NO_USER
    if not new_fact.strip():
        return "Nothing to save; provide the corrected fact."
    # Checked here, not left to the card: a card whose fact is gone still
    # files, and draws as "No longer applies".
    try:
        async with get_async_session() as session:
            saved = await saved_fact(user_id, old_fact, session=session)
    except ValueError as e:
        return f"{e} If it is new, save_memory it."
    return await _propose(
        "memory.update", {"old_fact": saved.fact, "new_fact": new_fact}
    )


async def forget_memory(fact: str) -> BaseModel | str:
    """Ask the user to approve dropping one saved fact - no longer true, or
    now readable by a tool. ``fact`` is a quote of the saved fact. Files an
    approval card: nothing is forgotten until the user approves it, so
    never say it is gone."""
    if (user_id := _user("forget_memory")) is None:
        return NO_USER
    try:  # as in update_memory
        async with get_async_session() as session:
            saved = await saved_fact(user_id, fact, session=session)
    except ValueError as e:
        return str(e)
    return await _propose("memory.forget", {"fact": saved.fact})


# Built-in registration: importing this module makes the tools grantable
# via the agent registry. replace=True keeps re-imports idempotent.
register_tool(
    "save_memory",
    save_memory,
    description="File a card asking to remember one durable fact about the user",
    effect="proposes",
    cards=True,
    replace=True,
)
register_tool(
    "replace_memory",
    replace_memory,
    description="File a card asking to replace all saved facts about the user",
    effect="proposes",
    cards=True,
    replace=True,
)
register_tool(
    "update_memory",
    update_memory,
    description="File a card asking to rewrite one saved fact that has changed",
    effect="proposes",
    cards=True,
    replace=True,
)
register_tool(
    "forget_memory",
    forget_memory,
    description="File a card asking to drop one saved fact",
    effect="proposes",
    cards=True,
    replace=True,
)
