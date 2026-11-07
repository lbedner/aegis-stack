"""Fake DNS and a recording web for ``app.core.safe_fetch``, so guarded
fetches are tested without the network: "refused" then means refused
before any connection, not refused by a closed port."""

from typing import Any

import httpx
import pytest

from app.core import safe_fetch


def resolving_to(monkeypatch: pytest.MonkeyPatch, *answers: list[str]) -> list[str]:
    """Each lookup takes the next answer (the last repeats). Returns the
    hosts asked."""
    asked: list[str] = []
    pending = list(answers)

    async def resolve(host: str, port: int) -> list[str]:
        asked.append(host)
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(safe_fetch, "_resolve", resolve)
    return asked


def answering(
    monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response
) -> list[httpx.Request]:
    """Every ``httpx.AsyncClient`` answers with the next response (the last
    repeats). Returns the requests that reached it."""
    sent: list[httpx.Request] = []
    pending = list(responses)
    real = httpx.AsyncClient

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return pending.pop(0) if len(pending) > 1 else pending[0]

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(answer), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return sent
