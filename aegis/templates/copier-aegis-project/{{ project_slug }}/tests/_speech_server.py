"""Stand-ins for a speech server of yours (Kokoro-FastAPI, the hearing
server): the settings a host shell has, the server answering by path, and
the server answering the real OpenAI client."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings

# Hearing models a hearing server holds (speaches' Parakeet first).
PARAKEET = "istupakov/parakeet-tdt-0.6b-v3-onnx"
WHISPER = "Systran/faster-whisper-small"
# What speaches answers: the hearing models it holds, and those in memory.
SPEACHES = {
    "/v1/models": {"object": "list", "data": [{"id": WHISPER}, {"id": PARAKEET}]},
    "/api/ps": {"models": [PARAKEET]},
}


class Shell:
    """Settings as a shell on the host has them, with only the speech
    settings given: this ships to every stack, and only inference and
    ai[voice] carry them."""

    is_docker = False
    localhost_url = staticmethod(Settings.localhost_url)

    def __init__(self, **given: Any) -> None:
        self.__dict__.update(given)


def openai_answering(
    monkeypatch: pytest.MonkeyPatch, answer: Callable[[], httpx.Response]
) -> list[httpx.Request]:
    """Every request the OpenAI client makes answered with ``answer()``;
    returns the requests, as they come."""
    import openai

    real = openai.AsyncOpenAI
    asked: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return answer()

    def client(**kw: Any) -> Any:
        stub = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        return real(http_client=stub, **kw)

    monkeypatch.setattr(openai, "AsyncOpenAI", client)
    return asked


def serving(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]
) -> list[httpx.Request]:
    """A server answering each request from ``answers``, by ``"METHOD
    path"`` or by path alone (a body, or a status code alone), 404 past
    them. Returns the requests that reached it."""
    sent: list[httpx.Request] = []
    real = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        path = request.url.path
        found = answers.get(f"{request.method} {path}", answers.get(path, 404))
        if isinstance(found, int):
            return httpx.Response(found)
        if isinstance(found, bytes):
            return httpx.Response(200, content=found)
        return httpx.Response(200, json=found)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(answer), **kw),
    )
    return sent


def unasked(
    monkeypatch: pytest.MonkeyPatch, server: Any, setting: str, url: str
) -> None:
    """``server``'s server at ``url`` (its ``setting``), not asked yet this
    process for what it holds (its ``LISTED``)."""
    from app.core.config import settings
    from app.services.ai.domains.voice import library

    monkeypatch.setattr(library, "TRIED", set())
    monkeypatch.setattr(server, "LISTED", {})
    monkeypatch.setattr(settings, setting, url)


async def listed(listing: Callable[..., list[Any]], provider_id: str) -> set[str]:
    """What ``listing`` has of ``provider_id``'s once the ask it starts is in."""
    from app.services.ai.domains.voice import library

    listing()
    await asyncio.gather(*library.LOADING)
    return {item.id for item in listing(provider_id)}
