"""Inference commands, on the speech server the component tracks
(``app.core.speech_server``), as Overseer > Inference > Speech and the
inference API:

- ``inference speech`` - what it reports, and its voices by accent and gender.
- ``inference speak "a line" -v af_heart`` - the line said, into an MP3.
- ``inference speech-model unload|reload`` - its model out of memory, or back.
- ``inference link-ollama`` - Ollama's GGUF models into llama-server's
  ``--models-dir`` (``app.components.inference.ollama_library``).
- ``inference llama`` - that folder served by a llama-server router, here
  (``make llama``).
- ``inference kokoro`` - Kokoro-FastAPI served from its checkout, here
  (``make kokoro``).
"""

import asyncio
import os
from pathlib import Path
import platform
import shutil
from typing import Annotated
from urllib.parse import urlsplit

import typer

from app.cli import theme
from app.components.inference.llamacpp import LlamaCppEngine, router_command
from app.components.inference.ollama_library import link_ollama as link
from app.core import speech_server
from app.core.config import settings

app = typer.Typer(
    name="inference",
    help="The local inference servers: the speech server, and llama.cpp's models.",
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


def _folders() -> tuple[Path, Path]:
    """Ollama's folder, and the one a llama-server router serves."""
    return (
        Path(settings.OLLAMA_MODELS).expanduser(),
        Path(settings.LLAMACPP_MODELS_DIR).expanduser(),
    )


async def _link(ollama: Path, folder: Path) -> None:
    linked = await asyncio.to_thread(link, folder, ollama)
    theme.good(f"Linked {len(linked)} of Ollama's models into {folder}")
    for name in linked:
        typer.echo(f"  {name}")


@app.command("link-ollama")
async def link_ollama() -> None:
    """Link Ollama's GGUF models into llama-server's --models-dir
    (LLAMACPP_MODELS_DIR)."""
    ollama, folder = _folders()
    if not (ollama / "manifests").is_dir():
        theme.fail(f"No Ollama models at {ollama} (OLLAMA_MODELS)")
    await _link(ollama, folder)
    typer.echo("Serve the folder: make llama")


@app.command()
async def llama() -> None:
    """Serve llama.cpp's models on this machine (make llama): Ollama's
    linked in when it is here, then this process becomes a llama-server
    router over LLAMACPP_MODELS_DIR, on LLAMACPP_BASE_URL's port, at
    LLAMACPP_CONTEXT, with LLAMACPP_ARGS. Ctrl-C stops it."""
    ollama, folder = _folders()
    if (ollama / "manifests").is_dir():
        await _link(ollama, folder)
    folder.mkdir(parents=True, exist_ok=True)
    argv = router_command(
        str(folder),
        urlsplit(LlamaCppEngine.configured_url()).port or 8080,
        settings.LLAMACPP_CONTEXT,
        settings.LLAMACPP_ARGS,
    )
    theme.good(" ".join(argv))
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        theme.fail("llama-server is not installed: brew install llama.cpp")


def _kokoro_start() -> list[str]:
    """Kokoro-FastAPI's start script for this machine, on its GPU where it
    has one: a Mac's, or an NVIDIA card's (``nvidia-smi`` on the PATH).
    Windows' scripts serve on 8880 whatever PORT says."""
    gpu = "gpu" if shutil.which("nvidia-smi") else "cpu"
    if platform.system() == "Windows":
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", f"start-{gpu}.ps1"]
    if platform.system() == "Darwin":
        gpu = "gpu_mac"
    return ["bash", f"start-{gpu}.sh"]


@app.command()
async def kokoro() -> None:
    """Serve Kokoro-FastAPI on this machine (make kokoro): its start script
    in SPEECH_SERVER_DIR (on its GPU where it has one), on SPEECH_BASE_URL's
    port, with the two flags that open its model and process to the
    Overseer. Ctrl-C stops it."""
    folder = Path(settings.SPEECH_SERVER_DIR).expanduser()
    argv = _kokoro_start()
    if not (folder / argv[-1]).is_file():
        theme.fail(
            f"No {speech_server.NAME} at {folder} (SPEECH_SERVER_DIR): "
            f"git clone https://github.com/remsky/Kokoro-FastAPI {folder}"
        )
    port = urlsplit(speech_server.reach(settings) or "").port or 8880
    # Its script runs uv itself: this project's venv would take its installs.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env |= {speech_server.DEV: "true", speech_server.DEBUG: "true", "PORT": str(port)}
    theme.good(f"{folder / argv[-1]} on port {port}")
    os.chdir(folder)
    os.execvpe(argv[0], argv, env)
