"""A hearing server you run, speaches first (``inference[speaches]``, or
any OpenAI-compatible transcription server at HEARING_BASE_URL): the
hearing models it holds, those in memory, and one loaded or unloaded.
Reaching it and calling it are the speech server's rules
(``speech_server.reach``, ``speech_server.call``).
"""

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core import series, speech_server
from app.core.figures import FIGURES, absent
from app.core.speech_server import WAIT_SECONDS, root

NAME = "speaches"
# Its id (the inference overview's, and its Overseer page's).
SLUG = "speaches"
SETTING = "HEARING_BASE_URL"
KIND = "hearing"
# speaches serves speech and embeddings too; these are its hearing models.
TASK = "automatic-speech-recognition"
# speaches' own route, past OpenAI's API: what is in memory (GET), and a
# model loaded (POST) or unloaded (DELETE).
PS = "api/ps"
ACTIONS = {"load": "POST", "unload": "DELETE"}
# What the inference sampler reads it as, and each transcription's point.
SAMPLER = "hearing"
CALLS = "stt"
LATENCY = f"{CALLS}:file:{series.LATENCY}"
ADD = f"aegis add inference[{SLUG}]"
HOW_TO_ADD = f"Run a hearing server and set {SETTING} in .env, or add {NAME}"
UNSET = f"No hearing server is set. {HOW_TO_ADD}: {ADD}."


class HearingServerReading(BaseModel):
    """The server as it answered: up or down, the hearing models it holds,
    those in memory (absent where it does not say: only speaches does), and
    why it could not be read."""

    model_config = FIGURES

    base_url: str
    available: bool
    models: list[str] = Field(default_factory=list)
    loaded: list[str] | None = absent()
    error: str | None = None

    def in_memory(self, model: str) -> bool | None:
        """Whether ``model`` is in memory; None where the server does not say."""
        return None if self.loaded is None else model in self.loaded


def reach(settings: Any) -> str | None:
    """Where this process reaches it (``speech_server.reach``)."""
    return speech_server.reach(settings, SETTING)


async def _loaded(client: httpx.AsyncClient, url: str) -> list[str] | None:
    """What is in memory, where the server says (speaches); None elsewhere,
    a page of its own in that route's place included."""
    answer = await client.get(f"{root(url)}/{PS}")
    try:
        return sorted(answer.json()["models"]) if answer.is_success else None
    except (ValueError, KeyError, TypeError):
        return None


async def read(url: str) -> HearingServerReading:
    """The server at ``url`` as it answers now; unavailable, and why, where
    it cannot be read."""
    try:
        async with httpx.AsyncClient(timeout=WAIT_SECONDS) as client:
            listed, loaded = await asyncio.gather(
                client.get(f"{url.rstrip('/')}/models", params={"task": TASK}),
                _loaded(client, url),
            )
        listed.raise_for_status()
        models = sorted(m["id"] for m in listed.json()["data"])
        return HearingServerReading(
            base_url=url,
            available=True,
            models=models,
            # Its hearing models only: speaches holds its voice-activity
            # model in memory beside them.
            loaded=None if loaded is None else [m for m in loaded if m in models],
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        return HearingServerReading(base_url=url, available=False, error=repr(e))


def figures(reading: HearingServerReading) -> list[tuple[str, str]]:
    """What it holds at a glance, labelled, leaving out what it does not
    say: Overseer's figures and the CLI's."""
    found = [("Models", str(len(reading.models)))]
    if reading.loaded is not None:
        found.append(("In memory", str(len(reading.loaded))))
    return found


def unanswered(url: str) -> str:
    """What to do where nothing answered at ``url``."""
    return speech_server.unanswered(url, KIND, SETTING)


async def move(url: str, action: str, model: str) -> None:
    """Load ``model`` into memory or unload it; ValueError for any other
    action than ``ACTIONS``, ``SpeechServerError`` where the server
    refuses or does not answer."""
    method = ACTIONS.get(action)
    if method is None:
        raise ValueError(f"No action {action}: load or unload.")
    await speech_server.call(f"{root(url)}/{PS}/{model}", method=method, kind=KIND)
