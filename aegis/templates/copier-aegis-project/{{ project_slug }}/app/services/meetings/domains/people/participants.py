"""Who was in a call: each participant is one of the owner's people across
their meetings (one name, one person, until someone says two are the
same), a name the model gave is found among them, the owner is whichever
of them is "me", and what the bot heard is kept per participant; and a
meeting nobody owns given to someone, its people with it (``give``)."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.calendar.owners import check_owner
from app.services.meetings.domains.people import queries
from app.services.meetings.domains.series import queries as series_queries
from app.services.meetings.models import (
    UNKNOWN,
    Meeting,
    MeetingParticipant,
    MeetingPerson,
)


async def participants(
    db: AsyncSession, meeting: Meeting, names: set[str]
) -> dict[str, int]:
    """The meeting's participant id for each display name, adding those it
    does not have yet, each as the owner's person already called so (as
    written, then ignoring case and spacing), or someone new."""
    if not names:
        return {}
    meeting_id: int = meeting.id  # type: ignore[assignment]
    known = {
        p.display_name: p
        for p in await queries.participants_named(db, meeting_id, names)
    }
    new = names - known.keys()
    people = await _people_for(db, meeting.owner_user_id, new)
    fresh = [
        MeetingParticipant(
            meeting_id=meeting_id, display_name=name, person_id=people[name]
        )
        for name in sorted(new)
    ]
    db.add_all(fresh)
    await db.flush()
    return {p.display_name: p.id for p in [*known.values(), *fresh]}  # type: ignore[misc]


async def _people_for(
    db: AsyncSession, owner_user_id: int | None, names: set[str]
) -> dict[str, int]:
    """The owner's person each of ``names`` is (as written, then ignoring
    case and spacing), someone new for a name they do not know."""
    people = await queries.people_known_as(db, owner_user_id, names)
    people |= await _known_loosely(db, owner_user_id, names - people.keys())
    newcomers = {
        name: MeetingPerson(owner_user_id=owner_user_id, name=name)
        for name in sorted(names - people.keys())
    }
    db.add_all(newcomers.values())
    await db.flush()
    return people | {name: p.id for name, p in newcomers.items()}  # type: ignore[misc]


class MeetingOwnedError(RuntimeError):
    """Someone owns the meeting already: only one nobody owns is given."""


async def give(db: AsyncSession, meeting: Meeting, user_id: int) -> None:
    """Give a meeting nobody owns (an agent joined it from its calendar and
    nobody on the invite has an account here) to ``user_id``, its people
    and notes with it; one someone owns is refused, as is an id nobody here
    has (``NoSuchOwnerError``)."""
    if meeting.owner_user_id is not None:
        raise MeetingOwnedError("Someone owns this meeting already")
    await check_owner(db, user_id)
    await _hand_over(db, meeting, user_id)
    link = series_queries.series_link(meeting.url)
    await series_queries.drop_if_empty(db, None, link)
    await db.commit()


async def _hand_over(db: AsyncSession, meeting: Meeting, owner_user_id: int) -> None:
    """Make the meeting ``owner_user_id``'s, its people with it: each the
    person the new owner already knows by that name, or someone new to
    them, and its note items theirs. Anyone left in no meeting goes."""
    meeting_id: int = meeting.id  # type: ignore[assignment]
    old = {
        person.id: person.name
        for _, person in await queries.meeting_people(db, meeting_id)
    }
    people = await _people_for(db, owner_user_id, set(old.values()))
    moved = {was: people[name] for was, name in old.items()}
    await queries.repoint_people(db, meeting_id, moved)  # type: ignore[arg-type]
    meeting.owner_user_id = owner_user_id
    db.add(meeting)
    await db.flush()
    await queries.drop_people_in_no_meeting(db, list(old))  # type: ignore[arg-type]


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


async def named(
    db: AsyncSession, meeting: Meeting, names: set[str]
) -> dict[str, int | None]:
    """Who each name the model gave is: someone in this meeting called so
    (as written, then ignoring case and spacing), else someone the owner
    already knows by that name; None for anyone else (the board, a
    customer), whose name stays as written."""
    here = await queries.meeting_people(db, meeting.id)  # type: ignore[arg-type]
    exact = {p.display_name: person.id for p, person in here}
    loose = {_key(p.display_name): person.id for p, person in here}
    rest = {n for n in names if _key(n) not in loose}
    elsewhere = await _known_loosely(db, meeting.owner_user_id, rest)
    return {n: exact.get(n, loose.get(_key(n), elsewhere.get(n))) for n in names}


async def _known_loosely(
    db: AsyncSession, owner_user_id: int | None, names: set[str]
) -> dict[str, int]:
    """The owner's person each of ``names`` is, ignoring case and spacing."""
    if not names:
        return {}
    known = {_key(p.name): p.id for p in await queries.owner_people(db, owner_user_id)}
    return {n: known[_key(n)] for n in names if _key(n) in known}  # type: ignore[misc]


async def set_me(db: AsyncSession, meeting_id: int, name: str | None) -> bool:
    """Say which speaker in the meeting the owner is: that person is "me"
    in every meeting, and no one else in this one is. None: none of this
    meeting's people is. False when nobody by ``name`` spoke in it."""
    here = await queries.meeting_people(db, meeting_id)
    picked = {person.id for p, person in here if p.display_name == name}
    if name is not None and not picked:
        return False
    others = {person.id for _, person in here} - picked
    await queries.mark_me(db, others, False)  # type: ignore[arg-type]
    await queries.mark_me(db, picked, True)  # type: ignore[arg-type]
    return True


def me_in(here: list[tuple[MeetingParticipant, MeetingPerson]]) -> str | None:
    """The speaker in a meeting (``here``: its people) who is the owner, by
    name."""
    return next((p.display_name for p, person in here if person.is_me), None)


async def keep_heard(
    db: AsyncSession, meeting_id: int, heard: dict[str, float]
) -> None:
    """Keep how many seconds of each speaker the bot heard: on each
    participant, and what no caption named on the meeting."""
    here = {p.display_name: p for p, _ in await queries.meeting_people(db, meeting_id)}
    for name, seconds in heard.items():
        if name in here:
            here[name].heard_seconds = seconds
    meeting = await db.get_one(Meeting, meeting_id)
    meeting.unattributed_seconds = (
        sum(s for name, s in heard.items() if name not in here) or None
    )
    db.add_all([meeting, *here.values()])
    await db.commit()


def heard_in(
    here: list[tuple[MeetingParticipant, MeetingPerson]], meeting: Meeting
) -> dict[str, float]:
    """Seconds heard of each speaker of ``meeting`` (``here``: its people),
    by name; what no caption named under ``UNKNOWN``."""
    heard = {p.display_name: p.heard_seconds for p, _ in here if p.heard_seconds}
    if meeting.unattributed_seconds:
        heard[UNKNOWN] = meeting.unattributed_seconds
    return heard  # type: ignore[return-value]
