"""The llama.cpp engine: a ``llama-server`` read into the neutral shapes
(``engine``).

A single-model server serves the one model it was started with (``-m``,
``-hf``), so that model is both what it has and what it runs, and it has no
load or unload. What the model is comes from ``/v1/models``' ``data[].meta``;
the Ollama-shaped ``models`` list beside it has every field empty, and
``/api/*`` is not there: it is not an Ollama server.
"""

import asyncio
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


def _served(
    listing: dict[str, Any], props: dict[str, Any]
) -> list[tuple[InferenceModel, int]]:
    """Each model, with the context it serves (``meta.n_ctx``)."""
    models = []
    for entry in listing.get("data", []):
        meta = entry.get("meta") or {}
        params = meta.get("n_params") or 0
        model = (
            InferenceModel(
                name=entry["id"],
                model=entry["id"],
                size=meta.get("size") or 0,
                details=ModelDetails(
                    format="gguf",
                    parameter_size=f"{params / 1e9:.1f}B" if params else "",
                    quantization_level=meta.get("ftype", ""),
                    context_length=meta.get("n_ctx_train") or 0,
                    embedding_length=meta.get("n_embd") or 0,
                ),
                capabilities=_capabilities(props),
            ),
            meta.get("n_ctx") or 0,
        )
        models.append(model)
    return models


class LlamaCppEngine(BaseInferenceEngine):
    """A local llama.cpp ``llama-server``, in single-model mode."""

    NAME = "llamacpp"
    LABEL = "llama.cpp"
    DEFAULT_URL = "http://localhost:8080"
    START = "llama-server --jinja -m <model.gguf>"
    can_load_unload = False

    async def _read(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """``/v1/models`` and ``/props``, read together."""
        async with self._client() as client:
            listing, props = await asyncio.gather(
                self._get(client, "/v1/models"), self._get(client, "/props")
            )
        return listing, props

    async def fetch_models(self) -> list[InferenceModel]:
        return [model for model, _ in _served(*await self._read())]

    async def _move(self, action: str, model_name: str) -> bool:
        """Nothing to move: it serves the model it was started with."""
        return False

    async def get_server_status(self) -> InferenceServerStatus:
        """A failed read (down, or still loading its model: 503) is
        "unavailable". Its one model is loaded, at the context it serves
        (``meta.n_ctx``)."""
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
                for m, context in served
            ],
            installed_models=[m for m, _ in served],
        )
