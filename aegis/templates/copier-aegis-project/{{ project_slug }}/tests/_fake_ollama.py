"""An Ollama server for tests (``app.components.inference``): one model
loaded and two installed, behind a client that answers without a network.
Shared by the inference component's tests and the Overseer Inference page's,
so it ships with the component, not with either frontend."""

from datetime import UTC, datetime, timedelta

import pytest

from app.components.inference.ollama import (
    OllamaClient,
    OllamaModel,
    OllamaModelDetails,
    OllamaRunningModel,
    OllamaServerStatus,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
DETAILS = OllamaModelDetails(
    parameter_size="7.6B", quantization_level="Q4_K_M", context_length=32768
)


def _installed(name: str) -> OllamaModel:
    return OllamaModel(
        name=name,
        model=name,
        size=4 * 1024**3,
        digest="0123456789abcdef" * 4,
        modified_at=NOW - timedelta(days=2),
        details=DETAILS,
        capabilities=["completion", "tools"],
    )


RUNNING = OllamaRunningModel(
    name="qwen2.5:7b",
    model="qwen2.5:7b",
    size=4 * 1024**3,
    size_vram=int(4.2 * 1024**3),
    digest="0123456789abcdef" * 4,
    details=DETAILS,
    expires_at=NOW + timedelta(minutes=30),
)
SERVING = OllamaServerStatus(
    available=True,
    version="0.12.3",
    running_models=[RUNNING],
    installed_models=[_installed("qwen2.5:7b"), _installed("llama3.1:8b")],
    total_vram_gb=4.2,
)


class FakeClient(OllamaClient):
    """The real client's dispatch (``move``) over faked server calls."""

    status = SERVING
    loaded: bool = True
    calls: list[tuple[str, str]] = []

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or "http://host.docker.internal:11434"

    async def get_server_status(self) -> OllamaServerStatus:
        return self.status

    async def load_model(self, model_name: str, keep_alive: str = "30m") -> bool:
        FakeClient.calls.append(("load", model_name))
        return self.loaded

    async def unload_model(self, model_name: str) -> bool:
        FakeClient.calls.append(("unload", model_name))
        return self.loaded


def serve(
    monkeypatch: pytest.MonkeyPatch, client: type[FakeClient] = FakeClient
) -> None:
    """Answer the inference sampler, the one reader of Ollama, with
    ``client``, and start the activity tracker afresh."""
    from app.components.inference import activity, sampler

    monkeypatch.setattr(sampler, "OllamaClient", client)
    monkeypatch.setattr(activity, "_tracker", activity.OllamaActivityTracker())
