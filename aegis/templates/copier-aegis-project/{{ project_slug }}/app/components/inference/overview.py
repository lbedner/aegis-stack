"""Every engine the inference component tracks, in one read: Overseer >
Inference's overview, the ``inference status`` command and
``GET /api/v1/inference`` all show it.

A row per engine: its job, whether it answers, what it holds, the memory it
reports and who runs on it. Each engine reports memory its own way (Ollama
each loaded model's, Kokoro-FastAPI its process's with its debug routes
on, llama.cpp's server and speaches none), so a row that reports nothing
says why, never 0. The engines' memory is not summed into the machine's:
the webserver runs in Docker and sees the VM, not the host the engines run
on, so the total is what the engines report together (``reported_bytes``).

Who runs on each is the AI service's to say (agents own their model, the
voice profile its speech), read through its facade where the stack has it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple

from pydantic import BaseModel, Field

from app.components.inference import ENGINES, inference_engine_class, sampler
from app.components.inference.engine import InferenceServerStatus
from app.core import discovery, hearing_server, series, speech_server
from app.core.config import settings
from app.core.figures import FIGURES, absent
from app.core.formatting import format_bytes

TEXT, SPEECH, HEARING = "Text", "Speech", "Hearing"
DOWN = "It is not answering."
UNREPORTED = "It does not report its memory."
NOTHING_REPORTED = "No engine reports its memory."
REPORTED = "Reported together"
STATES = {True: "Reachable", False: "Unreachable"}
USERS = "app.services.ai.service"
DB = "app.core.db"


class Engine(NamedTuple):
    """What an engine is: its id (its ``inference[...]`` name, or the speech
    or hearing server's slug), the name it goes by, and its job."""

    id: str
    name: str
    job: str


def text_engine() -> Engine:
    """The app's text engine (Ollama, or llama.cpp)."""
    engine = inference_engine_class()
    return Engine(engine.NAME, engine.LABEL, TEXT)


SPEECH_ENGINE = Engine(speech_server.SLUG, speech_server.NAME, SPEECH)
HEARING_ENGINE = Engine(hearing_server.SLUG, hearing_server.NAME, HEARING)


class LoadedModel(BaseModel):
    """A model an engine holds in memory, and how much where it says."""

    model_config = FIGURES

    name: str
    memory_bytes: int | None = absent()


class EngineRow(BaseModel):
    """One engine: ``id`` is an ``Engine``'s;
    ``memory_note`` says why there is no memory figure, or what one covers."""

    model_config = FIGURES

    id: str
    name: str
    job: str
    available: bool
    url: str | None = absent()
    loaded: list[LoadedModel] = Field(default_factory=list)
    memory_bytes: int | None = absent()
    memory_note: str | None = absent()
    used_by: list[str] = Field(default_factory=list)


class EngineToAdd(BaseModel):
    """An engine the app lacks, and how it gets one: a command or an
    address, never a button."""

    model_config = FIGURES

    name: str
    job: str
    how: str
    command: str


class InferenceOverview(BaseModel):
    """Every engine, the memory they report together, and those to add."""

    model_config = FIGURES

    engines: list[EngineRow]
    reported_bytes: int
    to_add: list[EngineToAdd] = Field(default_factory=list)


def memory_said(row: EngineRow) -> str:
    """A row's memory as it reads: the figure, else why there is none."""
    if row.memory_bytes is None:
        return row.memory_note or DOWN
    return format_bytes(row.memory_bytes)


def total_said(found: InferenceOverview) -> str:
    """The memory the engines report together, else that none does."""
    if all(row.memory_bytes is None for row in found.engines):
        return NOTHING_REPORTED
    return format_bytes(found.reported_bytes)


def loaded_said(model: LoadedModel) -> str:
    """A loaded model, with its memory where its engine says."""
    if model.memory_bytes is None:
        return model.name
    return f"{model.name} ({format_bytes(model.memory_bytes)})"


def holds_said(row: EngineRow) -> str:
    """Every model a row holds, else that it holds none."""
    return ", ".join(loaded_said(m) for m in row.loaded) or "Nothing"


def used_by_said(row: EngineRow) -> str:
    """Who runs on a row's engine, else that no one does."""
    return ", ".join(row.used_by) or "No one"


def _note(available: bool, unreported: str | None) -> str | None:
    """Why a row has no memory figure: it is down, else ``unreported``."""
    return DOWN if not available else unreported


def text_row(server: InferenceServerStatus, url: str) -> EngineRow:
    """The app's text engine, as its sampler last read it."""
    reports = server.available and inference_engine_class().REPORTS_MEMORY
    loaded = [
        LoadedModel(name=m.name, memory_bytes=m.size_vram if reports else None)
        for m in server.running_models
    ]
    return EngineRow(
        **text_engine()._asdict(),
        available=server.available,
        url=url,
        loaded=loaded,
        memory_bytes=sum(m.memory_bytes or 0 for m in loaded) if reports else None,
        memory_note=None if reports else _note(server.available, UNREPORTED),
    )


def speech_row(reading: speech_server.SpeechServerReading) -> EngineRow:
    """The speech server, as its sampler last read it."""
    memory = reading.memory_bytes
    closed = speech_server.DEBUG in reading.closed
    unreported = speech_server.left_off([speech_server.DEBUG]) if closed else UNREPORTED
    own = speech_server.own_models(reading) if reading.loaded else []
    return EngineRow(
        **SPEECH_ENGINE._asdict(),
        available=reading.available,
        url=reading.base_url,
        loaded=[LoadedModel(name=m) for m in own],
        memory_bytes=memory,
        memory_note=None if memory is not None else _note(reading.available, unreported),
    )


def hearing_row(reading: hearing_server.HearingServerReading) -> EngineRow:
    """The hearing server, as its sampler last read it."""
    return EngineRow(
        **HEARING_ENGINE._asdict(),
        available=reading.available,
        url=reading.base_url,
        loaded=[LoadedModel(name=m) for m in reading.loaded or []],
        memory_note=_note(reading.available, UNREPORTED),
    )


def _to_add(has_speech: bool, has_hearing: bool) -> list[EngineToAdd]:
    """The speech and hearing servers where none is set, and each other
    text engine (an app runs one, so adding another switches to it)."""
    current = inference_engine_class()
    found = [
        EngineToAdd(
            name=engine.LABEL,
            job=TEXT,
            how=f"Switch the app's text engine from {current.LABEL} to it.",
            command=f"aegis add inference[{engine.NAME}]",
        )
        for engine in ENGINES.values()
        if engine is not current
    ]
    servers = (
        (speech_server, SPEECH, has_speech),
        (hearing_server, HEARING, has_hearing),
    )
    found += [
        EngineToAdd(
            name=server.NAME, job=job, how=f"{server.HOW_TO_ADD}.", command=server.ADD
        )
        for server, job, has in servers
        if not has
    ]
    return found


def _engine_users() -> Callable[..., Awaitable[Any]] | None:
    """The AI service's read of who runs on each engine, where the stack
    has the service and its database."""
    return getattr(discovery.optional(USERS), "engine_users", None)


async def _users(session: Any, server: InferenceServerStatus) -> Any:
    """Who runs on each engine, or None without a database or the service."""
    read = _engine_users() if session is not None else None
    if read is None:
        return None
    served = {inference_engine_class().NAME: [m.name for m in server.installed_models]}
    return await read(session, served)


async def _readings(serving: bool) -> list[Any]:
    """The text engine, the speech server and the hearing server, together:
    in the webserver, the samplers' last readings (one read a tick for every
    viewer); anywhere else, read now, needing no Redis. A server not set is
    not read (None)."""
    read = series.reading if serving else _now

    async def unset() -> None:
        return None

    servers = (
        (sampler.SPEECH, speech_server.reach(settings)),
        (sampler.HEARING, hearing_server.reach(settings)),
    )
    return await asyncio.gather(
        read(sampler.SAMPLER), *(read(s) if url else unset() for s, url in servers)
    )


async def _now(each: series.Sampler) -> Any:
    return (await each.read()).latest


async def read_overview(session: Any, *, serving: bool = True) -> InferenceOverview:
    """Every engine now, and who runs on each where ``session`` is a
    database's; read from the sampled series where this process is the
    webserver (``serving``; a CLI command is not)."""
    (server, url), speech, heard = await _readings(serving)
    rows = [text_row(server, url)]
    if speech is not None:
        rows.append(speech_row(speech))
    if heard is not None:
        rows.append(hearing_row(heard))
    used = await _users(session, server)
    by: dict[str, list[str]] = {}
    for use in used.uses if used is not None else []:
        by.setdefault(use.engine, []).append(use.by)
    engines = [r.model_copy(update={"used_by": by.get(r.id, [])}) for r in rows]
    return InferenceOverview(
        engines=engines,
        reported_bytes=sum(r.memory_bytes or 0 for r in engines),
        to_add=_to_add(speech is not None, heard is not None),
    )


async def current_overview(*, serving: bool = True) -> InferenceOverview:
    """``read_overview`` in a session of its own where the stack has a
    database (the API's and the CLI's: an entry point opens the one)."""
    db = discovery.optional(DB)
    if db is None:
        return await read_overview(None, serving=serving)
    async with db.get_async_session(read_only=True) as session:
        return await read_overview(session, serving=serving)
