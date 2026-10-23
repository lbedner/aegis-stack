"""The system model built once the app has started, off the event loop:
every part has registered by then, so the first reader (a map, a flow
card, the ontology tool) finds it whole and built, never parsing the
source mid-request."""

import asyncio

from fastapi import FastAPI
import pytest

from app.components.backend.hooks import backend_hooks
from app.core import concurrency
from app.integrations import main


async def test_it_is_built_once_every_startup_hook_has_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []

    async def hooks() -> None:
        ran.append("hooks")

    async def nothing() -> None:
        return None

    monkeypatch.setattr(backend_hooks, "discover_lifespan_hooks", nothing)
    monkeypatch.setattr(backend_hooks, "execute_startup_hooks", hooks)
    monkeypatch.setattr(backend_hooks, "execute_shutdown_hooks", nothing)
    monkeypatch.setattr(main.flet_fastapi.app_manager, "start", nothing)
    monkeypatch.setattr(main.flet_fastapi.app_manager, "shutdown", nothing)
    monkeypatch.setattr(main.ontology, "current", lambda: ran.append("model"))

    async with main.lifespan(FastAPI()):
        await asyncio.gather(*concurrency._background)

    assert ran == ["hooks", "model"]
