"""A speech server you run, Kokoro-FastAPI first (``inference[kokoro_fastapi]``,
or any at SPEECH_BASE_URL): where this process reaches it, what it lists and
reports of itself, a line said in one of its voices, and its model unloaded
or reloaded. The one client for it: the inference component tracks it (its
health, its sampler, Overseer > Inference > Speech, the ``inference`` CLI
and API) and ai[voice] lists its voices.

A server with OpenAI's API alone reports its models and voices; what
Kokoro-FastAPI reports past them (its version, its model's state, its
process) is read where it answers, and a flag that keeps it closed (a 403)
is named so the reader knows what to turn on.
"""

import asyncio
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core import series
from app.core.figures import FIGURES, absent
from app.core.formatting import format_bytes, format_span

NAME = "Kokoro-FastAPI"
# What it is called on the Docker network: the host, or its own compose
# service (``inference[docker,kokoro_fastapi]``).
DOCKER_HOSTS = {"host.docker.internal", "kokoro-fastapi"}
# A local server answers at once; Ollama's client waits as long.
WAIT_SECONDS = 2.0
# A line takes as long as it is to say, and a model reload as long as a load.
SAY_SECONDS = 60.0
# OpenAI's name for its speech model, which a compatible server takes too,
# and all of OpenAI's names a server may answer to as aliases of its own.
MODEL = "tts-1"
OPENAI_MODELS = {MODEL, "tts-1-hd", "gpt-4o-mini-tts"}
# What a voice says when it is played with no line of its own, and the
# voice a line is said in when none is named (Kokoro's own default).
LINE = "Hello. This is how I sound, reading a line for you."
VOICE = "af_heart"
# What the inference sampler reads it as, and each call's points (``say``,
# ai[voice]'s ``local_server``): a whole file, or a stream until its first
# audio.
SAMPLER = "speech"
CALLS = "tts"
LATENCY = {kind: f"{CALLS}:{kind}:{series.LATENCY}" for kind in ("file", "stream")}
ACTIONS = ("unload", "reload")
# Kokoro-FastAPI's flags: its dev routes (its model's state, unload and
# reload) and its debug routes (its process).
DEV = "ALLOW_DEV_UNLOAD"
DEBUG = "ENABLE_DEBUG_ENDPOINTS"
# What it reports at its root past OpenAI's API, by the flag that opens it
# (none: always open).
REPORTS = {"web/config": None, "dev/model": DEV, "debug/threads": DEBUG}
# What each flag opens, for the reader told to turn it on.
OPENS = {DEV: "its model's state, unload and reload", DEBUG: "its memory and threads"}
UNSET = (
    f"No speech server is set: run {NAME} and set SPEECH_BASE_URL, or add "
    "inference[kokoro_fastapi]."
)
# Kokoro's voice names say their accent and gender (``af_heart``).
ACCENTS = {
    "a": "General American",
    "b": "British",
    # Its other languages, which a speech server running it speaks too.
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Brazilian Portuguese",
    "z": "Mandarin",
}
GENDERS = {"f": "female", "m": "male"}
# A report a flag keeps shut: Kokoro-FastAPI answers 403.
_CLOSED = object()


class SpeechServerReading(BaseModel):
    """The server as it answered: up or down, the models and voices it
    lists, what it reports of itself (absent where it does not), the flags
    left off that keep the rest closed, and why it could not be read."""

    model_config = FIGURES

    base_url: str
    available: bool
    models: list[str] = Field(default_factory=list)
    voices: list[str] = Field(default_factory=list)
    version: str | None = absent()
    backend: str | None = absent()
    device: str | None = absent()
    loaded: bool | None = absent()
    active_requests: int | None = absent()
    idle_seconds: float | None = absent()
    unloads_in: float | None = absent()
    memory_bytes: int | None = absent()
    threads: int | None = absent()
    closed: list[str] = Field(default_factory=list)
    error: str | None = None


class SpeechServerError(Exception):
    """A call the server refused or never answered, said for its caller;
    ``flag`` is the one left off where that is why (Kokoro-FastAPI's 403)."""

    def __init__(self, message: str, flag: str | None = None) -> None:
        super().__init__(message)
        self.flag = flag


def reach(settings: Any) -> str | None:
    """SPEECH_BASE_URL as this process reaches it: a shell on the host swaps
    a Docker name for localhost, on the port ``make serve`` published it on
    (SPEECH_HOST_PORT). Only inference and ai[voice] carry the two
    settings; elsewhere there is no server."""
    url = getattr(settings, "SPEECH_BASE_URL", None)
    if not url or settings.is_docker:
        return url
    port = getattr(settings, "SPEECH_HOST_PORT", None)
    return settings.localhost_url(url, DOCKER_HOSTS, port)


def _root(url: str) -> str:
    """The server itself, where its own routes are: ``url`` less ``/v1``."""
    return url.rstrip("/").removesuffix("/v1")


async def _get(client: httpx.AsyncClient, url: str, path: str) -> Any:
    answer = await client.get(f"{url.rstrip('/')}/{path}")
    answer.raise_for_status()
    return answer.json()


async def _report(client: httpx.AsyncClient, root: str, path: str) -> Any:
    """What the server reports at ``path``: its answer, ``_CLOSED`` where a
    flag keeps it shut, None where it has no such route."""
    answer = await client.get(f"{root}/{path}")
    if answer.status_code == httpx.codes.FORBIDDEN:
        return _CLOSED
    return answer.json() if answer.is_success else None


def _names(listing: Any) -> list[str]:
    # Kokoro-FastAPI's legacy answer is the names alone.
    return sorted(v if isinstance(v, str) else v["id"] for v in listing["voices"])


async def voices(url: str) -> list[str]:
    """The voices the server at ``url`` lists; raises where it cannot be
    read. Voices alone, so a server that cannot list its models still
    speaks."""
    async with httpx.AsyncClient(timeout=WAIT_SECONDS) as client:
        return _names(await _get(client, url, "audio/voices"))


def left_off(closed: list[str]) -> str:
    """What to start the server with to report the rest (``closed``, a
    reading's); empty with nothing closed."""
    if not closed:
        return ""
    flags = " and ".join(f"{flag}=true ({OPENS[flag]})" for flag in closed)
    return f"Start {NAME} with {flags} to see the rest."


def unanswered(url: str) -> str:
    """What to do where nothing answered at ``url``."""
    return f"No speech server answered at {url}. Start it, or check SPEECH_BASE_URL."


def _shown(pairs: list[tuple[str, Any]]) -> list[tuple[str, str]]:
    return [(label, str(value)) for label, value in pairs if value not in (None, "")]


def figures(reading: SpeechServerReading) -> list[tuple[str, str]]:
    """What the server reports of itself at a glance, labelled, leaving out
    what it does not: Overseer's figures and the CLI's."""
    loaded, memory = reading.loaded, reading.memory_bytes
    return _shown(
        [
            ("Version", reading.version),
            ("Model", None if loaded is None else "Loaded" if loaded else "Unloaded"),
            ("Device", reading.device),
            ("In flight", reading.active_requests),
            ("Memory", None if memory is None else format_bytes(memory)),
            ("Voices", len(reading.voices)),
        ]
    )


def facts(reading: SpeechServerReading) -> list[tuple[str, str]]:
    """The rest of what it reports, labelled, leaving out what it does not:
    Overseer's Server card and the CLI's. OpenAI's model names are aliases
    where the server has a model of its own."""
    own = [m for m in reading.models if m not in OPENAI_MODELS]
    aliases = [m for m in reading.models if m in OPENAI_MODELS] if own else []
    return _shown(
        [
            ("Backend", reading.backend),
            ("Models", ", ".join(own or reading.models)),
            ("Aliases", ", ".join(aliases)),
            ("Idle for", format_span(reading.idle_seconds)),
            ("Unloads in", format_span(reading.unloads_in)),
            ("Threads", reading.threads),
        ]
    )


def _reported(found: dict[str, Any]) -> dict[str, Any]:
    """The reading's fields from what the server reported, by route (a
    route closed or missing reports nothing)."""
    config, model, process = (
        found[path] if isinstance(found[path], dict) else {} for path in REPORTS
    )
    memory = process.get("memory_mb")
    return {
        "version": config.get("version"),
        "backend": model.get("backend"),
        "device": model.get("device"),
        "loaded": model.get("loaded"),
        "active_requests": model.get("active_requests"),
        "idle_seconds": model.get("idle_seconds"),
        "unloads_in": model.get("seconds_until_auto_unload"),
        "memory_bytes": None if memory is None else int(memory * 2**20),
        "threads": process.get("total_threads"),
    }


async def read(url: str) -> SpeechServerReading:
    """The server at ``url`` as it answers now; unavailable, and why, where
    it cannot be read."""
    try:
        async with httpx.AsyncClient(timeout=WAIT_SECONDS) as client:
            models, listing, *reports = await asyncio.gather(
                _get(client, url, "models"),
                _get(client, url, "audio/voices"),
                *(_report(client, _root(url), path) for path in REPORTS),
            )
        found = dict(zip(REPORTS, reports, strict=True))
        return SpeechServerReading(
            base_url=url,
            available=True,
            models=sorted(m["id"] for m in models["data"]),
            voices=_names(listing),
            closed=[
                flag for p, flag in REPORTS.items() if found[p] is _CLOSED and flag
            ],
            **_reported(found),
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
        return SpeechServerReading(base_url=url, available=False, error=repr(e))


async def charted(kind: str, seconds: float) -> None:
    """A call to the server charted with how long it took, on success only:
    a failure's time says nothing of its speed."""
    await series.record({LATENCY[kind]: seconds})


async def _post(url: str, body: Any = None, flag: str | None = None) -> bytes:
    """What the server answers a POST to ``url`` with; ``SpeechServerError``
    where it does not, naming ``flag`` where that keeps the route shut (403)."""
    try:
        async with httpx.AsyncClient(timeout=SAY_SECONDS) as client:
            answer = await client.post(url, json=body)
    except httpx.HTTPError as exc:
        raise SpeechServerError(f"The speech server did not answer: {exc!r}") from exc
    if flag and answer.status_code == httpx.codes.FORBIDDEN:
        raise SpeechServerError(left_off([flag]), flag)
    if not answer.is_success:
        raise SpeechServerError(f"The speech server refused ({answer.status_code}).")
    return answer.content


async def say(url: str, text: str, voice: str) -> bytes:
    """``text`` said in ``voice`` by the server at ``url``, as an MP3;
    ``SpeechServerError`` where it cannot."""
    body = {"model": MODEL, "input": text, "voice": voice, "response_format": "mp3"}
    started = time.perf_counter()
    audio = await _post(f"{url.rstrip('/')}/audio/speech", body)
    await charted("file", time.perf_counter() - started)
    return audio


async def move(url: str, action: str) -> None:
    """Unload the server's model or load it again; ValueError for any other
    action than ``ACTIONS``, ``SpeechServerError`` where the server refuses."""
    if action not in ACTIONS:
        raise ValueError(f"No action {action}: unload or reload.")
    await _post(f"{_root(url)}/dev/{action}", flag=DEV)


def traits(name: str) -> tuple[str, str] | None:
    """A Kokoro voice's accent and gender, as its name says
    (``af_heart``: General American, female); None where it does not."""
    accent, gender = ACCENTS.get(name[:1]), GENDERS.get(name[1:2])
    return (accent, gender) if accent and gender and name[2:3] == "_" else None


def grouped(names: list[str]) -> list[tuple[str, list[str]]]:
    """``names`` by accent and gender (``"British, female"``), each group
    where its first voice is; those whose names say neither under Other."""
    groups: dict[str, list[str]] = {}
    for name in names:
        said = traits(name)
        groups.setdefault(", ".join(said) if said else "Other", []).append(name)
    return list(groups.items())
