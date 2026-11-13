"""An Ollama server for tests (``app.components.inference``): one model
loaded and two installed, behind a client that answers without a network.
Shared by the inference component's tests and the Overseer Inference page's,
so it ships with the component, not with either frontend."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.components.inference.engine import (
    InferenceModel,
    InferenceServerStatus,
    ModelDetails,
    RunningModel,
)
from app.components.inference.ollama import OllamaEngine

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
DETAILS = ModelDetails(
    parameter_size="7.6B", quantization_level="Q4_K_M", context_length=32768
)


def _installed(name: str) -> InferenceModel:
    return InferenceModel(
        name=name,
        model=name,
        size=4 * 1024**3,
        digest="0123456789abcdef" * 4,
        modified_at=NOW - timedelta(days=2),
        details=DETAILS,
        capabilities=["completion", "tools"],
    )


RUNNING = RunningModel(
    name="qwen2.5:7b",
    model="qwen2.5:7b",
    size=4 * 1024**3,
    size_vram=int(4.2 * 1024**3),
    digest="0123456789abcdef" * 4,
    details=DETAILS,
    expires_at=NOW + timedelta(minutes=30),
)
SERVING = InferenceServerStatus(
    available=True,
    version="0.12.3",
    running_models=[RUNNING],
    installed_models=[_installed("qwen2.5:7b"), _installed("llama3.1:8b")],
    total_vram_gb=4.2,
)


class FakeClient(OllamaEngine):
    """The real client's dispatch (``move``) over faked server calls."""

    status = SERVING
    loaded: bool = True
    calls: list[tuple[str, str]] = []

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "http://host.docker.internal:11434"

    async def get_server_status(self) -> InferenceServerStatus:
        return self.status

    async def _move(self, action: str, model_name: str) -> bool:
        FakeClient.calls.append((action, model_name))
        return self.loaded


def serve(
    monkeypatch: pytest.MonkeyPatch, client: type[FakeClient] = FakeClient
) -> None:
    """Answer every caller of ``get_inference_engine`` with ``client``,
    and start the activity tracker afresh."""
    from app.components import inference
    from app.components.inference import activity

    monkeypatch.setitem(inference.ENGINES, "ollama", client)
    monkeypatch.setattr(activity, "_tracker", activity.ActivityTracker())


# The same server over HTTP, by path: what the engine contract test reads
# through the real ``OllamaEngine``.
ROUTES = {
    "/api/version": {"version": SERVING.version},
    "/api/tags": {
        "models": [m.model_dump(mode="json") for m in SERVING.installed_models]
    },
    "/api/ps": {"models": [RUNNING.model_dump(mode="json")]},
}


def serving(routes: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """A ``MockTransport`` handler answering each path from ``routes``."""
    return lambda request: httpx.Response(200, json=routes[request.url.path])


def down(request: httpx.Request) -> httpx.Response:
    """A ``MockTransport`` handler for a server that is not there."""
    raise httpx.ConnectError("refused", request=request)
