"""Memory writes as proposals on the change queue: ``memory.save``,
``memory.replace``, ``memory.update`` and ``memory.forget``.

Untrusted text reaches the assistant - an email body, a document, a
fetched page - and a fact saved on its say-so is a lasting instruction in
every later prompt, as a fact forgotten on its say-so is a standing
instruction gone. So a memory write is a card like every other write, and
nothing changes until the user approves it. The tools that file them are
``user_memory``'s.
"""

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.figures import FIGURES
from app.services.ai.domains.chat import queries, user_memory
from app.services.ai.domains.chat.user_memory import UserFact
from app.services.ai.models.agents import AgentUserMemory
from app.services.change_queue.queue import FILING
from app.services.change_queue.registry import ChangeExecutor, register
from app.services.change_queue.schemas import ChangeDisplayRow


class _ForTheTurnsUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Whose memory: never the model's to say, so not in its contract.
    user_id: SkipJsonSchema[str] = ""

    @model_validator(mode="before")
    @classmethod
    def _the_turns(cls, data: Any, info: ValidationInfo) -> Any:
        # Through the generic ``propose`` a model (an MCP client's too)
        # could name anyone's memory: filed, it is the turn's user's,
        # whatever the payload says, and none without one. A stored payload
        # re-validated at approval stands.
        if info.context != FILING or not isinstance(data, dict):
            return data
        bound = user_memory.current_user_id.get()
        if not bound:
            raise ValueError("a memory change is only for the user this turn is for")
        return {**data, "user_id": bound}


class SavePayload(_ForTheTurnsUser):
    fact: str = Field(description="The fact to remember, in a sentence")
    category: str = Field(
        "general", description="Its category; an unknown one files as general"
    )

    @field_validator("category")
    @classmethod
    def _known(cls, category: str) -> str:
        # The card shows the category it will be filed under.
        return user_memory._normalize_category(category)


class ReplacePayload(_ForTheTurnsUser):
    memory_text: str = Field(description="Every fact to keep, one per line")


class UpdatePayload(_ForTheTurnsUser):
    old_fact: str = Field(description="A quote of the saved fact")
    new_fact: str = Field(description="The fact as it reads now")


class ForgetPayload(_ForTheTurnsUser):
    fact: str = Field(description="A quote of the saved fact")


class Remembered(BaseModel):
    """What an approved memory change did, in words."""

    model_config = FIGURES

    memory: str


async def _facts(
    db: AsyncSession, payloads: list[_ForTheTurnsUser]
) -> dict[str, list[UserFact]]:
    """Each named user's saved facts, in one read however many cards."""
    users = {p.user_id for p in payloads}
    rows = await queries.user_memories_for(db, users)
    saved = {row.user_id: user_memory.facts_of(row) for row in rows}
    return {u: saved.get(u, []) for u in users}


def _for(payload: _ForTheTurnsUser) -> ChangeDisplayRow:
    """Whose memory the card changes."""
    return ChangeDisplayRow(label="For", value=payload.user_id)


async def save_execute(
    db: AsyncSession, payload: SavePayload, owner_user_id: int | None
) -> Remembered:
    said = await user_memory.save_user_fact(
        payload.user_id, payload.fact, payload.category, session=db
    )
    return Remembered(memory=said)


async def save_describe(
    db: AsyncSession, payloads: list[SavePayload], owner_user_id: int | None
) -> list[list[ChangeDisplayRow]]:
    return [
        [
            _for(p),
            ChangeDisplayRow(label="Remember", value=p.fact.strip()),
            ChangeDisplayRow(label="Category", value=p.category),
        ]
        for p in payloads
    ]


async def replace_execute(
    db: AsyncSession, payload: ReplacePayload, owner_user_id: int | None
) -> Remembered:
    said = await user_memory.replace_user_memory(
        payload.user_id, payload.memory_text, session=db
    )
    return Remembered(memory=said)


async def replace_describe(
    db: AsyncSession, payloads: list[ReplacePayload], owner_user_id: int | None
) -> list[list[ChangeDisplayRow]]:
    saved = await _facts(db, payloads)
    return [
        [
            _for(p),
            ChangeDisplayRow(
                label="Forget", value=f"all {len(saved[p.user_id])} saved fact(s)"
            ),
            ChangeDisplayRow(label="Remember instead", value=p.memory_text.strip()),
        ]
        for p in payloads
    ]


# Update and forget name their fact by its words: positions move between a
# card and its approval. A fact no longer there refuses (ValueError), and
# the card says it no longer applies.
async def update_execute(
    db: AsyncSession, payload: UpdatePayload, owner_user_id: int | None
) -> Remembered:
    entry = await user_memory.update_user_fact(
        payload.user_id, payload.old_fact, fact=payload.new_fact, session=db
    )
    return Remembered(memory=f"Updated ({entry.category}): {entry.fact}")


async def update_describe(
    db: AsyncSession, payloads: list[UpdatePayload], owner_user_id: int | None
) -> list[list[ChangeDisplayRow]]:
    saved = await _facts(db, payloads)
    return [
        [
            _for(p),
            ChangeDisplayRow(
                label="Was",
                value=user_memory.fact_matching(saved[p.user_id], p.old_fact).fact,
            ),
            ChangeDisplayRow(label="Now", value=p.new_fact.strip()),
        ]
        for p in payloads
    ]


async def forget_execute(
    db: AsyncSession, payload: ForgetPayload, owner_user_id: int | None
) -> Remembered:
    gone = await user_memory.delete_user_fact(payload.user_id, payload.fact, session=db)
    return Remembered(memory=f"Forgot: {gone.fact}")


async def forget_describe(
    db: AsyncSession, payloads: list[ForgetPayload], owner_user_id: int | None
) -> list[list[ChangeDisplayRow]]:
    saved = await _facts(db, payloads)
    return [
        [
            _for(p),
            ChangeDisplayRow(
                label="Forget",
                value=user_memory.fact_matching(saved[p.user_id], p.fact).fact,
            ),
        ]
        for p in payloads
    ]


for change_type, title, model, execute, describe, description in (
    (
        "memory.save",
        "Remember a fact",
        SavePayload,
        save_execute,
        save_describe,
        "Keep one durable fact about the user for later conversations.",
    ),
    (
        "memory.replace",
        "Replace everything remembered",
        ReplacePayload,
        replace_execute,
        replace_describe,
        "Replace every saved fact about the user, one fact per line.",
    ),
    (
        "memory.update",
        "Change a remembered fact",
        UpdatePayload,
        update_execute,
        update_describe,
        "Rewrite one saved fact that has changed, in place.",
    ),
    (
        "memory.forget",
        "Forget a remembered fact",
        ForgetPayload,
        forget_execute,
        forget_describe,
        "Drop one saved fact that is no longer true.",
    ),
):
    register(
        ChangeExecutor(
            change_type=change_type,
            title=title,
            payload_model=model,
            execute=execute,
            describe=describe,
            description=description,
            object=AgentUserMemory,
        )
    )
