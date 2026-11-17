"""The llama.cpp engine: a ``llama-server`` read into the neutral shapes
(``engine``).

A single-model server serves the one model it was started with (``-m``,
``-hf``), so that model is both what it has and what it runs, and it has no
load or unload. What the model is comes from ``/v1/models``' ``data[].meta``;
the Ollama-shaped ``models`` list beside it has every field empty, and
``/api/*`` is not there: it is not an Ollama server.

A router (``--models-dir``; ``/props`` says ``role: router``) serves every
model in that folder and in llama.cpp's download cache, loading and freeing
them on request (``/models/load``, ``/models/unload``). Its ``/v1/models``
gives each one's status and trained context; what one is beyond that is
known only once it is loaded.
"""

import asyncio
import shlex
from typing import Any

import httpx

from app.components.inference.engine import (
    BaseInferenceEngine,
    InferenceModel,
    InferenceServerStatus,
    ModelDetails,
    RunningModel,
)


def _capabilities(props: dict[str, Any]) -> list[str]:
    """What the chat template and the loaded model take, as Ollama names them."""
    caps = ["completion"]
    if props.get("chat_template_caps", {}).get("supports_tool_calls"):
        caps.append("tools")
    if props.get("modalities", {}).get("vision"):
        caps.append("vision")
    return caps


def _routing(listing: dict[str, Any]) -> bool:
    """A router lists each model with its status; one model, without."""
    return any("status" in entry for entry in listing.get("data", []))


def _warm(entry: dict[str, Any]) -> bool:
    """In memory: a router's model when its status says so; a single-model
    server's one model whenever it answers."""
    status = entry.get("status")
    return status is None or status.get("value") == "loaded"


def _served(
    listing: dict[str, Any], props: dict[str, Any]
) -> list[tuple[InferenceModel, bool, int]]:
    """Each model, whether it is in memory, and the context it serves
    (``meta.n_ctx``; a router knows only the trained one, unloaded)."""
    models = []
    for entry in listing.get("data", []):
        meta = entry.get("meta") or {}
        params = meta.get("n_params") or 0
        model = InferenceModel(
            name=entry["id"],
            model=entry["id"],
            size=meta.get("size") or 0,
            details=ModelDetails(
                format="gguf",
                parameter_size=f"{params / 1e9:.1f}B" if params else "",
                quantization_level=meta.get("ftype", ""),
                context_length=meta.get("n_ctx_train")
                or entry.get("context_length")
                or 0,
                embedding_length=meta.get("n_embd") or 0,
            ),
            capabilities=_capabilities(props),
        )
        models.append((model, _warm(entry), meta.get("n_ctx") or 0))
    return models


def router_command(folder: str, port: int, context: int, extra: str = "") -> list[str]:
    """A llama-server router over ``folder``, with the flags chat needs
    (``make llama`` runs it); ``extra`` is any further flags, as typed."""
    return [
        "llama-server",
        "--models-dir",
        folder,
        "--jinja",
        "-c",
        str(context),
        "--metrics",
        "--port",
        str(port),
        *shlex.split(extra),
    ]


class LlamaCppEngine(BaseInferenceEngine):
    """A local llama.cpp ``llama-server``: a router, or one model."""

    NAME = "llamacpp"
    LABEL = "llama.cpp"
    DEFAULT_URL = "http://localhost:8080"
    START = " ".join(router_command("<folder>", 8080, 32768))
    ADD_MODEL = "a .gguf in its --models-dir (make llama links Ollama's in)"

    async def _read(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """``/v1/models`` and ``/props``, read together."""
        async with self._client() as client:
            listing, props = await asyncio.gather(
                self._get(client, "/v1/models"), self._get(client, "/props")
            )
        return listing, props

    async def fetch_models(self) -> list[InferenceModel]:
        return [model for model, _, _ in _served(*await self._read())]

    async def _move(self, action: str, model_name: str) -> None:
        """A router's ``/models/load`` or ``/models/unload``; a single-model
        server has neither (it serves the model it was started with), and
        refuses."""
        await self._post(f"/models/{action}", {"model": model_name}, 60.0)

    async def _holds(self, client: httpx.AsyncClient, model: str) -> bool:
        """Whether ``model`` is in memory (``_warm``); a single-model server
        answers on its one, whatever the turn calls it (it fails while it
        loads)."""
        listing = await self._get(client, "/v1/models")
        entries = listing.get("data", [])
        if not _routing(listing):
            return True
        return any(e["id"] == model and _warm(e) for e in entries)

    async def get_server_status(self) -> InferenceServerStatus:
        """A failed read (down, or still loading its model: 503) is
        "unavailable". A single-model server's one model is loaded; a
        router's are as it says, and it loads and frees them."""
        try:
            listing, props = await self._read()
        except (httpx.HTTPError, ValueError):
            return InferenceServerStatus(available=False)
        served = _served(listing, props)
        return InferenceServerStatus(
            available=True,
            version=props.get("build_info"),
            running_models=[
                RunningModel(
                    name=m.name,
                    model=m.model,
                    size=m.size,
                    details=m.details,
                    context_length=context,
                )
                for m, warm, context in served
                if warm
            ],
            installed_models=[m for m, _, _ in served],
            can_load_unload=_routing(listing),
        )
