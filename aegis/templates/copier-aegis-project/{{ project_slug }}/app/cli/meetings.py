"""``meetings``: the calls the bot was asked to join, from the terminal.

Meetings added here have no owner, the way a project without auth keeps
everything.
"""

from rich.table import Table
import typer

from app.cli import theme
from app.core.db import get_async_session
from app.core.formatting import format_clock, format_relative_time
from app.services.meetings.bot import run_meeting
from app.services.meetings.service import (
    DEFAULT_BOT_NAME,
    MeetingNotFoundError,
    MeetingsService,
    UnsupportedMeetingLinkError,
)

app = typer.Typer(help="Calls the meeting bot joins, and what was said in them.")
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
    bot_name: str = typer.Option(
        DEFAULT_BOT_NAME, "--bot-name", help="The name the bot joins as"
    ),
) -> None:
    """Send the bot into a meeting and stay with it until it leaves (Ctrl-C
    takes it out)."""
    async with get_async_session() as session:
        try:
            meeting = await MeetingsService(session, owner_user_id=None).request(
                url, bot_name
            )
        except UnsupportedMeetingLinkError as exc:
            theme.fail(str(exc))
    console.print(f"Meeting {meeting.id}: joining as {bot_name}...")
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


@app.command()
async def show(meeting_id: int = typer.Argument(..., help="The meeting's id")) -> None:
    """One meeting: its status and its transcript."""
    async with get_async_session() as session:
        svc = MeetingsService(session, owner_user_id=None)
        try:
            meeting = await svc.get(meeting_id)
        except MeetingNotFoundError as exc:
            theme.fail(str(exc))
        lines = await svc.transcript(meeting_id)
    console.print(f"Meeting {meeting.id}  {meeting.platform}  {meeting.url}")
    console.print(f"Status: {meeting.status}")
    if meeting.failure_reason:
        console.print(f"Reason: {meeting.failure_reason}")
    console.print(f"Bot: {meeting.bot_name}")
    console.print(f"Requested {format_relative_time(meeting.created_at)}")
    if not lines:
        console.print("[dim]No transcript yet.[/dim]")
    for speaker, line in lines:
        console.print(
            f"[dim]{format_clock(line.start_seconds)}[/dim] {speaker}: {line.text}"
        )
