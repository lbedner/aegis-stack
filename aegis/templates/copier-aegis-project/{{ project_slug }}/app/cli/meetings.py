"""``meetings``: the calls the bot was asked to join, from the terminal.

Meetings added here have no owner, the way a project without auth keeps
everything.
"""

from itertools import groupby
from pathlib import Path
import shlex

from rich.table import Table
import typer

from app.cli import theme
from app.core import secrets
from app.core.audit import cli_actor
from app.core.config import settings
from app.core.db import get_async_session
from app.core.formatting import format_clock, format_relative_time
from app.services.meetings.domains.accounts.service import (
    DEFAULT_AGENT,
    AgentNameError,
    AgentNotFoundError,
    check_name,
    keep_agent,
    login_secret_for,
    pick,
)
from app.services.meetings.domains.actions import tokens
from app.services.meetings.domains.actions.runner import Runner, run_forever, run_once
from app.services.meetings.domains.bot.login import (
    LoginError,
    capture_login,
    find_chrome,
    save_login,
)
from app.services.meetings.domains.bot.run import run_meeting
from app.services.meetings.domains.moments import tidy
from app.services.meetings.models import MeetingRecord, Notes, SeriesRecord
from app.services.meetings.service import (
    NOTHING_FOUND,
    MeetingNotFoundError,
    MeetingsService,
    SearchHit,
    SeriesNotFoundError,
    SeriesService,
    UnsupportedMeetingLinkError,
    note_points,
    said_when,
    search_meetings,
)

app = typer.Typer(help="Calls the meeting bot joins, and what was said in them.")
runner_tokens = typer.Typer(help="Tokens a runner on another machine claims runs with.")
app.add_typer(runner_tokens, name="runner-token")
console = theme.console()


@app.command("list")
async def list_meetings(
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """The meetings, newest first."""
    async with get_async_session() as session:
        rows = await MeetingsService(session, owner_user_id=None).list_meetings(limit)
    table = Table(title="Meetings")
    for column in ("ID", "Platform", "Status", "Bot", "Requested", "Link"):
        table.add_column(column)
    for m in rows:
        table.add_row(
            str(m.id),
            m.platform,
            m.status,
            m.bot_name,
            format_relative_time(m.created_at),
            m.url,
        )
    console.print(table)


@app.command()
async def join(
    url: str = typer.Argument(..., help="The meeting link"),
    agent: str | None = typer.Option(
        None, "--agent", help="The agent to send (the default if not given)"
    ),
    bot_name: str = typer.Option(
        "", "--bot-name", help="The name it joins as (the agent's own if not given)"
    ),
) -> None:
    """Send the bot into a meeting and stay with it until it leaves (Ctrl-C
    takes it out)."""
    async with get_async_session() as session:
        try:
            account = await pick(session, agent)
            meeting = await MeetingsService(session, owner_user_id=None).request(
                url, bot_name or account.display_name, account.id
            )
        except (UnsupportedMeetingLinkError, AgentNotFoundError) as exc:
            theme.fail(str(exc))
    console.print(f"Meeting {meeting.id}: joining as {meeting.bot_name}...")
    await run_meeting(meeting.id)  # type: ignore[arg-type]
    async with get_async_session() as session:
        done = await MeetingsService(session, owner_user_id=None).get(meeting.id)  # type: ignore[arg-type]
    console.print(f"Meeting {done.id}: {done.status}")
    if done.failure_reason:
        theme.fail(done.failure_reason)


@app.command()
async def leave(meeting_id: int = typer.Argument(..., help="The meeting's id")) -> None:
    """Ask the bot to leave a meeting it is in."""
    async with get_async_session() as session:
        try:
            meeting = await MeetingsService(session, owner_user_id=None).ask_to_leave(
                meeting_id
            )
        except MeetingNotFoundError as exc:
            theme.fail(str(exc))
    console.print(f"Meeting {meeting.id}: {meeting.status}")


def describe(record: MeetingRecord) -> list[str]:
    """One meeting as ``show`` prints it: the service's read, as the pages
    say it."""
    meeting = record.meeting
    facts = [
        ("Status", record.status),
        ("Reason", meeting.failure_reason),
        ("Length", record.length),
        ("Heard", record.heard),
        ("Bot", meeting.bot_name),
    ]
    return [
        f"Meeting {meeting.id}  {meeting.platform}  {meeting.url}",
        *[f"{label}: {value}" for label, value in facts if value],
        f"Requested {format_relative_time(meeting.created_at)}",
        *_notes(record.notes),
        *[
            f"[dim]{format_clock(row.at)}[/dim] {row.speaker}: {row.text}"
            for row in record.transcript
        ],
        *([] if record.transcript else ["[dim]No transcript yet.[/dim]"]),
    ]


def _part(title: str, points: list[str]) -> list[str]:
    """A part of the notes or a series, its title over its points; nothing
    when it has none."""
    return [f"[bold]{title}[/bold]", *points] if points else []


def _point(text: str, *said: str | None) -> str:
    """One point, with what is said of it (whose, when due, where it
    stands) after it."""
    extra = ", ".join(s for s in said if s)
    return f"  {text} ({extra})" if extra else f"  {text}"


def _notes(notes: Notes | None) -> list[str]:
    """The notes as they read: the summary, then each part's points."""
    points = note_points(notes) if notes else []
    return [
        line
        for part, said in groupby(points, key=lambda p: p.part)
        for line in _part(
            part, [_point(p.text, p.who, p.due and f"due {p.due}") for p in said]
        )
    ]


def found(hits: list[SearchHit]) -> list[str]:
    """What ``search`` prints: each hit where it was said, as the pages
    label it, then who said it (or its part of the notes) and the text."""
    if not hits:
        return [f"[dim]{NOTHING_FOUND}[/dim]"]
    return [
        f"{said_when(hit.meeting_id, hit.at)}  {hit.speaker or hit.part}: {hit.text}"
        for hit in hits
    ]


def series_lines(record: SeriesRecord) -> list[str]:
    """One series as ``series`` prints it: its headline, its run over time,
    what it keeps coming back to and where each stands, its meetings."""
    series = record.series
    return [
        f"Series {series.id}  {record.name}",
        *([series.summary] if series.summary else []),
        *[
            line
            for section in (*record.over_time, *record.sections)
            for line in _part(
                section.title, [_point(i.text, i.status) for i in section.items]
            )
        ],
        f"Meetings: {', '.join(map(str, record.meetings))}",
    ]


@app.command()
async def show(meeting_id: int = typer.Argument(..., help="The meeting's id")) -> None:
    """One meeting: its status, who was heard, its notes and its transcript."""
    async with get_async_session() as session:
        try:
            record = await MeetingsService(session, owner_user_id=None).read(meeting_id)
        except MeetingNotFoundError as exc:
            theme.fail(str(exc))
    for line in describe(record):
        console.print(line)


@app.command()
async def search(
    query: str = typer.Argument(..., help="Words said, or a question"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """What was said with any of the words, those with the most first."""
    async with get_async_session() as session:
        hits = await search_meetings(session, None, query, limit)
    for line in found(hits):
        console.print(line)


@app.command("series")
async def series_of(
    series_id: int | None = typer.Argument(None, help="A series' id"),
) -> None:
    """The series (a recurring meeting read over time), or one in full."""
    async with get_async_session() as session:
        svc = SeriesService(session, owner_user_id=None)
        if series_id is None:
            rows = await svc.series()
        else:
            try:
                record = await svc.read(series_id)
            except SeriesNotFoundError as exc:
                theme.fail(str(exc))
    if series_id is not None:
        for line in series_lines(record):
            console.print(line)
        return
    table = Table(title="Series")
    for column in ("ID", "Name", "Meetings", "Written"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            str(row.series.id),
            row.name,
            str(row.series.meetings),
            format_relative_time(row.series.written_at),
        )
    console.print(table)


@app.command()
async def login(
    agent: str = typer.Option(
        DEFAULT_AGENT, "--agent", help="The agent to sign in (made if new)"
    ),
    name: str | None = typer.Option(
        None, "--name", help="The name it joins as: its Google account's"
    ),
    email: str | None = typer.Option(
        None, "--email", help="Its Google account's email"
    ),
    chrome: str | None = typer.Option(
        None, "--chrome", help="The Chrome to sign in with (found if not given)"
    ),
) -> None:
    """Sign one of the bot's own Google accounts in, once: Meet turns away a
    bot that is not signed in. Each agent is a Google account of its own."""
    try:
        check_name(agent)
        secrets.writable_store(login_secret_for(agent))
    except (AgentNameError, secrets.SecretsReadOnlyError) as exc:
        theme.fail(str(exc))
    chrome = chrome or find_chrome()
    if chrome is None:
        theme.fail("No Chrome found: give its path with --chrome.")
    console.print(
        "In the Chrome window that opens, sign in to the bot's own Google "
        "account (never your own), then quit Chrome (Cmd+Q / Ctrl+Q)."
    )
    try:
        state = await capture_login(chrome)
    except LoginError as exc:
        theme.fail(str(exc))
    async with get_async_session() as session:
        account = await keep_agent(session, agent, name, email)
    await save_login(state, actor=cli_actor(), secret=account.login_secret)
    console.print(f"Kept. {account.name} joins signed in from now on.")


@app.command()
async def runner(
    command: str = typer.Option(
        ...,
        "--command",
        help="The command each run runs; {prompt} is its prompt (stdin without it)",
    ),
    action: list[str] = typer.Option(
        ["agent"], "--action", help="An action this runner runs (repeat for more)"
    ),
    repo: Path | None = typer.Option(
        None, "--repo", help="Answer from a fresh worktree of this repository"
    ),
    ref: str = typer.Option(Runner.ref, "--ref", help="What each worktree checks out"),
    url: str | None = typer.Option(None, "--url", help="The app (API_BASE_URL)"),
    token: str = typer.Option(
        ...,
        "--token",
        envvar="MEETINGS_RUNNER_TOKEN",
        help="A runner token (meetings runner-token create)",
    ),
    once: bool = typer.Option(
        False, "--once", help="Answer one waiting run, then stop"
    ),
    poll: float = typer.Option(
        Runner.poll_seconds, "--poll", help="Seconds between looks while idle"
    ),
) -> None:
    """Claim the runs of ``--action`` asked in meetings and answer each with
    ``--command``, from a fresh worktree of ``--repo``, posting back what it
    printed. Runs where the repository and the agent's login are, holding a
    runner token: e.g. ``--command 'claude -p {prompt} --permission-mode plan'``."""
    found = Runner(
        url=url or settings.API_BASE_URL,
        token=token,
        actions=action,
        command=shlex.split(command),
        repo=repo.expanduser() if repo else None,
        ref=ref,
        poll_seconds=poll,
    )
    console.print(f"Answering {', '.join(action)} for {found.url}. Ctrl-C stops.")
    if once:
        console.print("Answered one." if await run_once(found) else "Nothing waits.")
        return
    await run_forever(found)


@app.command("look-over")
async def look_over(
    meeting_ids: list[int] | None = typer.Argument(None, help="The meetings' ids"),
    series: int | None = typer.Option(None, "--series", help="A series' meetings"),
    every: bool = typer.Option(False, "--all", help="Every meeting"),
) -> None:
    """Read kept calls over again for moments (questions first): ones kept
    before they were looked for, or after a detector changed. What is found
    now is kept; what no longer is goes, unless something was asked of it.
    Where the stack has a model, each call's questions are then cleaned up."""
    async with get_async_session() as session:
        if not (meeting_ids or series is not None or every):
            theme.fail("Name meetings, a --series or --all.")
        try:
            wanted = meeting_ids or await tidy.meeting_ids_of(session, series)
        except LookupError as exc:
            theme.fail(str(exc))
        await tidy.look_over(session, wanted)
    console.print(f"Read {len(wanted)} meeting(s) over.")


@runner_tokens.command("create")
async def create_token(
    name: str = typer.Argument(..., help="The runner's name (its machine)"),
    owner: int | None = typer.Option(
        None, "--owner", help="Whose runs it claims (every owner's without one)"
    ),
) -> None:
    """A token for a runner. Its value is shown this once."""
    async with get_async_session() as session:
        row, value = await tokens.create(session, owner, name)
    console.print(f"Runner token {row.name} ({row.hint}...), shown this once:")
    console.print(value, soft_wrap=True)


@runner_tokens.command("list")
async def list_tokens(
    owner: int | None = typer.Option(None, "--owner", help="Whose tokens"),
) -> None:
    """The runner tokens not revoked, newest first."""
    async with get_async_session() as session:
        rows = await tokens.live(session, owner)
    table = Table("Id", "Name", "Token", "Made", "Last used")
    for row in rows:
        table.add_row(
            str(row.id),
            row.name,
            f"{row.hint}...",
            format_relative_time(row.created_at),
            format_relative_time(row.last_used_at) if row.last_used_at else "never",
        )
    console.print(table)


@runner_tokens.command("revoke")
async def revoke_token(
    token_id: int = typer.Argument(..., help="The token's id (runner-token list)"),
    owner: int | None = typer.Option(None, "--owner", help="Whose token"),
) -> None:
    """Revoke a runner token: its runner is refused from now."""
    async with get_async_session() as session:
        try:
            await tokens.revoke(session, token_id, owner)
        except tokens.RunnerTokenNotFoundError:
            theme.fail(f"No live runner token {token_id}.")
    console.print(f"Revoked runner token {token_id}.")
