"""Inference commands, on the speech server the component tracks
(``app.core.speech_server``), as Overseer > Inference > Speech and the
inference API:

- ``inference speech`` - what it reports, and its voices by accent and gender.
- ``inference speak "a line" -v af_heart`` - the line said, into an MP3.
- ``inference speech-model unload|reload`` - its model out of memory, or back.
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from app.cli import theme
from app.core import speech_server
from app.core.config import settings

app = typer.Typer(
    name="inference",
    help="The local inference servers: the speech server.",
    no_args_is_help=True,
)


def _url() -> str:
    """Where the speech server is; exits saying how to set one where none is."""
    if url := speech_server.reach(settings):
        return url
    theme.fail(speech_server.UNSET)


@app.command()
async def speech() -> None:
    """What the speech server reports, and its voices by accent and gender."""
    reading = await speech_server.read(_url())
    if not reading.available:
        theme.fail(f"{speech_server.unanswered(reading.base_url)} ({reading.error})")
    theme.good(f"{speech_server.NAME} at {reading.base_url}")
    found = speech_server.figures(reading) + speech_server.facts(reading)
    for label, value in found:
        typer.echo(f"  {label}: {value}")
    for group, names in speech_server.grouped(reading.voices):
        typer.echo(f"  {group}: {', '.join(names)}")
    if hint := speech_server.left_off(reading.closed):
        theme.warn(hint)


@app.command()
async def speak(
    text: Annotated[str, typer.Argument(help="The line to say.")],
    voice: Annotated[
        str, typer.Option("--voice", "-v", help="One of the server's voices.")
    ] = speech_server.VOICE,
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Where the MP3 goes.")
    ] = Path("speech.mp3"),
) -> None:
    """Say a line in one of the speech server's voices, into an MP3."""
    try:
        audio = await speech_server.say(_url(), text, voice)
    except speech_server.SpeechServerError as exc:
        theme.fail(str(exc))
    await asyncio.to_thread(out.write_bytes, audio)
    theme.good(f"Said in {voice}: {out}")


@app.command("speech-model")
async def speech_model(
    action: Annotated[str, typer.Argument(help="unload or reload")],
) -> None:
    """Unload the speech server's model, or load it again."""
    try:
        await speech_server.move(_url(), action)
    except (ValueError, speech_server.SpeechServerError) as exc:
        theme.fail(str(exc))
    theme.good(f"{speech_server.NAME}: {action}ed")
