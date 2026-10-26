"""The agents: the Google accounts the bot joins calls as, each its own name
in the call and its own sign-in (``login``), kept under its own secret.

There is always one: the first is made the first time any are read, with
the sign-in a stack had before agents (``LOGIN``), and every meeting sent
before them becomes its. It is the one a meeting is sent as when none is
named. Another is made by signing it in (``meetings login --agent``).
Agents are the app's, not an owner's: any owner may send any of them.
"""

from collections.abc import Iterable
from datetime import datetime
import json
import re
import time
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import secrets
from app.core.log import logger
from app.services.meetings.domains.bot.card import initials
from app.services.meetings.domains.bot.login import LOGIN, signed_in
from app.services.meetings.domains.calendar.owners import check_owner
from app.services.meetings.models import IN_PROGRESS, AgentImage, BotAccount
from app.services.meetings.service import DEFAULT_BOT_NAME

from .queries import (
    drop_image,
    every_account,
    give_unsent_meetings,
    meetings_in,
    with_images,
)
from .queries import image_named as image_named

DEFAULT_AGENT = "notetaker"
# Typed on a command line and kept in a secret's name.
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SIGNED_IN, SIGNED_OUT, NOT_SIGNED_IN = "Signed in", "Signed out", "Not signed in"
# Kept, but not a sign-in the bot can use: not one, or will not decrypt.
UNREADABLE = "Unreadable"


class AgentNotFoundError(LookupError):
    """No agent by that name."""


class AgentNameError(ValueError):
    """A name an agent cannot have."""


# An agent's on/off settings, by field, with how the Overseers name them:
# whether it shows its card in a call, and whether anyone in one (not only
# the meeting's owner) may ask it something by name.
Switch = Literal["camera", "answers_anyone"]
SWITCHES: dict[Switch, str] = {"camera": "Camera", "answers_anyone": "Answers anyone"}
# What a browser draws on the card, and the most a picture may weigh.
IMAGE_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
)
IMAGE_NAMES = ", ".join(
    sorted(t.split("/")[1].split("+")[0].upper() for t in IMAGE_TYPES)
)
MOST_IMAGE_MB = 5
MOST_IMAGE_BYTES = MOST_IMAGE_MB * 1_000_000


class AgentImageError(ValueError):
    """A picture the card cannot carry: not one a browser draws, or too big."""


class AgentRow(BaseModel):
    """One agent as Overseer shows it: whether its sign-in still works, the
    meetings it is in (or on its way into or out of) now, and when its
    picture last changed (None without one: its card shows its
    ``initials``), which the picture's address carries so a browser keeps
    one until it changes."""

    account: BotAccount
    sign_in: str
    in_now: list[int]
    image: datetime | None
    initials: str


def secret_for(secret: str, name: str) -> str:
    """Where the agent called ``name`` keeps ``secret`` (its sign-in, its
    calendar): the first's under ``secret``, another's under
    ``<secret>__<NAME>``."""
    return secret if name == DEFAULT_AGENT else f"{secret}__{name.upper()}"


def login_secret_for(name: str) -> str:
    """Where the agent called ``name`` keeps its sign-in."""
    return secret_for(LOGIN, name)


def agent_names(every: Iterable[tuple[int, str]]) -> dict[int | None, str]:
    """Each agent's name by its id, from (id, name) in ``agents`` order; a
    meeting sent without one is the default's (the first)."""
    names: dict[int | None, str] = dict(every)
    return names | ({None: next(iter(names.values()))} if names else {})


def check_name(name: str) -> None:
    if not NAME.fullmatch(name):
        raise AgentNameError(
            f"{name!r} cannot name an agent: up to 40 lowercase letters, "
            "digits and dashes, starting with a letter or digit."
        )


async def agents(db: AsyncSession) -> list[BotAccount]:
    """Every agent, the default first; the first is made if there is none."""
    return await every_account(db) or await _first(db)


async def _first(db: AsyncSession) -> list[BotAccount]:
    """The first agent, on the sign-in kept before agents, with every
    meeting sent before them. Made once: another process may get there
    first, and then its is the one."""
    first = BotAccount(
        name=DEFAULT_AGENT, display_name=DEFAULT_BOT_NAME, login_secret=LOGIN
    )
    db.add(first)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return await every_account(db)
    assert first.id is not None
    await give_unsent_meetings(db, first.id)
    await db.commit()
    return [first]


async def pick(
    db: AsyncSession, name: str | None, every: list[BotAccount] | None = None
) -> BotAccount:
    """The agent called ``name`` (of ``every`` when the caller has read
    them already); the default when none is named."""
    every = every or await agents(db)
    if not name:
        return every[0]
    found = next((a for a in every if a.name == name), None)
    if found is None:
        known = ", ".join(a.name for a in every)
        raise AgentNotFoundError(f"No agent called {name}: there is {known}")
    return found


async def keep_agent(
    db: AsyncSession, name: str, display_name: str | None, email: str | None
) -> BotAccount:
    """The agent called ``name``, made if new, with the name it joins as
    and its Google account's email where given."""
    check_name(name)
    account = next((a for a in await agents(db) if a.name == name), None)
    if account is None:
        account = BotAccount(
            name=name,
            display_name=display_name or DEFAULT_BOT_NAME,
            login_secret=login_secret_for(name),
        )
    account.display_name = display_name or account.display_name
    account.email = email or account.email
    db.add(account)
    await db.commit()
    return account


async def set_default_owner(
    db: AsyncSession, name: str, user_id: int | None
) -> BotAccount:
    """Who owns a meeting the agent called ``name`` joins from its calendar
    when nobody on the invite has an account here (None: nobody);
    ``NoSuchOwnerError`` for an id nobody here has."""
    if user_id is not None:
        await check_owner(db, user_id)
    account = await pick(db, name)
    account.default_owner_id = user_id
    db.add(account)
    await db.commit()
    return account


async def set_switch(
    db: AsyncSession, name: str, switch: Switch, on: bool
) -> BotAccount:
    """One of the on/off settings (``SWITCHES``) of the agent called
    ``name``."""
    account = await pick(db, name)
    setattr(account, switch, on)
    db.add(account)
    await db.commit()
    return account


async def set_image(
    db: AsyncSession, name: str, data: bytes, content_type: str
) -> BotAccount:
    """The picture on the card of the agent called ``name``, over any it
    had; ``AgentImageError`` for one a browser does not draw or past
    ``MOST_IMAGE_BYTES``."""
    if content_type not in IMAGE_TYPES:
        raise AgentImageError(f"A card takes {IMAGE_NAMES}, not {content_type}")
    if len(data) > MOST_IMAGE_BYTES:
        raise AgentImageError(f"A card's picture is at most {MOST_IMAGE_MB} MB")
    account = await pick(db, name)
    await drop_image(db, account.id)  # type: ignore[arg-type]
    db.add(AgentImage(account_id=account.id, content_type=content_type, data=data))  # type: ignore[arg-type]
    await db.commit()
    return account


async def clear_image(db: AsyncSession, name: str) -> None:
    """The agent called ``name`` back to its initials."""
    account = await pick(db, name)
    await drop_image(db, account.id)  # type: ignore[arg-type]
    await db.commit()


async def sent_as(db: AsyncSession, account_id: int | None) -> BotAccount:
    """The agent a meeting was sent as; the default for one sent before
    agents."""
    account = await db.get(BotAccount, account_id) if account_id is not None else None
    return account or (await agents(db))[0]


async def overview(db: AsyncSession) -> list[AgentRow]:
    """Every agent with its sign-in and where it is now: one read of the
    secrets for all of them, one query for the meetings."""
    every = await agents(db)
    now = time.time()
    states = await _sign_ins([a.login_secret for a in every], now)
    busy = await meetings_in(db, IN_PROGRESS)
    pictured = await with_images(db, [a.id for a in every])  # type: ignore[misc]
    return [
        AgentRow(
            account=a,
            sign_in=states[a.login_secret],
            # A meeting sent without one is the default's.
            in_now=[m for owner, m in busy if (owner or every[0].id) == a.id],
            image=pictured.get(a.id),  # type: ignore[arg-type]
            initials=initials(a.display_name),
        )
        for a in every
    ]


async def _sign_ins(names: list[str], now: float) -> dict[str, str]:
    """Each secret's sign-in state, read at once; a row that will not
    decrypt fails the whole read, so then each is read alone."""
    try:
        kept = await secrets.get_many(*names)
    except secrets.SecretUnreadableError:
        return {name: await _sign_in(name, now) for name in names}
    return {name: sign_in_state(name, kept[name], now) for name in names}


async def _sign_in(name: str, now: float) -> str:
    try:
        return sign_in_state(name, await secrets.get(name), now)
    except secrets.SecretUnreadableError as exc:
        logger.warning("Meeting agent sign-in unreadable", secret=name, error=str(exc))
        return UNREADABLE


def sign_in_state(secret: str, kept: str | None, now: float) -> str:
    """A sign-in kept as ``secret``, as Overseer says it: signed in while
    Google's session has not expired. Only Google knows whether it still
    lets the bot in."""
    if not kept:
        return NOT_SIGNED_IN
    try:
        return SIGNED_IN if signed_in(json.loads(kept), now) else SIGNED_OUT
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning(
            "Meeting agent sign-in is not one", secret=secret, error=str(exc)
        )
        return UNREADABLE
