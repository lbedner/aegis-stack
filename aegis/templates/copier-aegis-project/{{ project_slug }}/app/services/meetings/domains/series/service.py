"""Each series of meetings, read and written again for one owner
(``owner_user_id``; ``None`` reads every owner's, as Overseer does): what
it keeps coming back to, each theme with every line it was said in, and
beside a meeting's own threads, the themes it is part of."""

from collections.abc import Callable, Coroutine
import importlib
from importlib.util import find_spec
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.concurrency import background
from app.core.formatting import counted
from app.services.meetings.domains.people.queries import quotes
from app.services.meetings.domains.series import queries
from app.services.meetings.domains.series.kept import PARTS, notes_of
from app.services.meetings.models import (
    OVER_TIME,
    Meeting,
    MeetingSeries,
    NoteItem,
    Quote,
    SeriesRecord,
    SeriesRow,
    Theme,
    ThreadItem,
    ThreadSection,
)
from app.services.meetings.service import NothingToWriteError

# The model pass that writes a series: only a stack with a model to ask
# has the module.
THEMES = "app.services.meetings.domains.series.themes"
# The series (owner and link) this process is writing now.
THEMING: set[tuple[int | None, str]] = set()
# ponytail: the latest meetings only, so the prompt stays bounded; a
# running summary would carry older ones if a series needs them.
MEETINGS = 10
LIMIT = 200
THEMES_KEY = "themes"


class SeriesNotFoundError(LookupError):
    """No such series for this owner."""


class SeriesService:
    def __init__(self, db: AsyncSession, owner_user_id: int | None) -> None:
        self.db = db
        self.owner_user_id = owner_user_id

    async def series(self) -> list[SeriesRow]:
        """The owner's series, latest written first."""
        found = await queries.series_of(self.db, self.owner_user_id, LIMIT)
        return [SeriesRow(series=s, name=series_name(s)) for s in found]

    async def get(self, series_id: int) -> MeetingSeries:
        found = await queries.one_series(self.db, self.owner_user_id, series_id)
        if found is None:
            raise SeriesNotFoundError(f"Series {series_id} not found")
        return found

    async def read(self, series_id: int) -> SeriesRecord:
        """The series in full: its meetings and its themes, each with every
        line it was said in."""
        series = await self.get(series_id)
        owner, link = series.owner_user_id, series.link
        notes = await notes_of(self.db, series)
        lines = {n for kind in PARTS for p in getattr(notes, kind) for n in p.lines}
        cited = await quotes(self.db, lines)
        meetings = [
            m.id for m in await queries.meetings_on(self.db, owner, link, MEETINGS)
        ]
        writing = (owner, link) in THEMING
        return SeriesRecord(
            series=series,
            name=series_name(series),
            meetings=meetings,  # type: ignore[arg-type]
            over_time=[
                ThreadSection(
                    key=kind,
                    title=title,
                    items=[_point(kind, p, cited) for p in getattr(notes, kind)],
                )
                for kind, title in OVER_TIME.items()
                if getattr(notes, kind)
            ],
            sections=[themes_section([_theme(t, cited) for t in notes.themes])],
            writing=writing,
            can_write=themes_writer() is not None and not writing and bool(meetings),
        )

    async def write_again(self, series_id: int) -> SeriesRecord:
        """Start writing the series over from its latest meetings, in the
        background; the read it returns says it is being written."""
        record = await self.read(series_id)
        write = themes_writer()
        if write is None or not record.can_write:
            raise NothingToWriteError("This series cannot be written now")
        THEMING.add((record.series.owner_user_id, record.series.link))
        background(write(record.meetings[0]))
        return record.model_copy(update={"writing": True, "can_write": False})


def series_name(series: MeetingSeries) -> str:
    """What a series is called: its calendar event's title, else its link."""
    return series.name or series.link


async def meeting_themes(db: AsyncSession, meeting: Meeting) -> ThreadSection:
    """What the meeting's series keeps coming back to that came up in it:
    its own lines of each, the series' other meetings' beside them."""
    link = queries.series_link(meeting.url)
    series = await queries.series_row(db, meeting.owner_user_id, link)
    themes = [] if series is None else (await notes_of(db, series)).themes
    cited = await quotes(db, {n for t in themes for n in t.lines})
    items = [_theme(t, cited, meeting.id) for t in themes]
    return themes_section([i for i in items if i.quotes], other="In other meetings")


def themes_section(items: list[ThreadItem], other: str | None = None) -> ThreadSection:
    return ThreadSection(
        key=THEMES_KEY,
        title="Keeps coming up",
        other=other,
        empty="Nothing has come up in more than one meeting yet.",
        items=items,
    )


def _theme(
    theme: Theme, cited: dict[int, Quote], here: int | None = None
) -> ThreadItem:
    """A theme as a thread: in how many meetings, where it stands; its
    lines, each with who said it (no names on the theme itself: one raised
    by everyone would read as a list of them), or, in meeting ``here``, its
    lines there and the other meetings' as its other lines."""
    said = [cited[n] for n in theme.lines if n in cited]
    meetings = {q.meeting_id for q in said}
    return ThreadItem(
        meeting_id=said[0].meeting_id if said else 0,
        text=theme.text,
        detail=counted(len(meetings), "meeting"),
        status=theme.status,
        quotes=[q for q in said if here is None or q.meeting_id == here],
        other=[] if here is None else [q for q in said if q.meeting_id != here],
    )


def _point(kind: str, point: NoteItem, cited: dict[int, Quote]) -> ThreadItem:
    """A point of the run as its card shows it: when (``_when``), and the
    lines it rests on."""
    said = [cited[n] for n in point.lines if n in cited]
    meetings = sorted({q.meeting_id for q in said})
    return ThreadItem(
        meeting_id=meetings[0] if meetings else 0,
        text=point.text,
        detail=_when(kind, meetings),
        quotes=said,
    )


def _when(kind: str, meetings: list[int]) -> str | None:
    """Since when it is open, from when to when it shifted, else the
    meeting it was last said in."""
    if not meetings:
        return None
    first, last = meetings[0], meetings[-1]
    if kind == "still_open":
        return f"Since meeting {first}"
    if kind == "shifted" and first != last:
        return f"Meetings {first} → {last}"
    return f"Meeting {last}"


def themes_writer() -> Callable[[int], Coroutine[Any, Any, None]] | None:
    """What writes a meeting's series, where the stack has a model to."""
    if find_spec(THEMES) is None:
        return None
    return importlib.import_module(THEMES).write_themes
