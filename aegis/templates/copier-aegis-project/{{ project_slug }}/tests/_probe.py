"""A provider for ``app.core.secrets.probe`` to ask, answering as told and
recording what it was sent, so key checks are tested without the network."""

import httpx
import pytest

from app.core import secrets


def answering(
    monkeypatch: pytest.MonkeyPatch, status: int, body: str = ""
) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, text=body)

    monkeypatch.setattr(
        secrets,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return sent
