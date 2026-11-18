"""The Ollama engine: its native ``/api`` read into the neutral shapes
(``engine``), and models loaded and freed through ``/api/generate``."""

import asyncio

import httpx
from pydantic import BaseModel, ConfigDict

from app.components.inference.engine import (
    BaseInferenceEngine,
    InferenceModel,
    InferenceServerStatus,
    RunningModel,
)
from app.core.log import logger


class _Tags(BaseModel):
    """``/api/tags``: the installed models."""

    model_config = ConfigDict(extra="ignore")

    models: list[InferenceModel] = []


class _Ps(BaseModel):
    """``/api/ps``: the models in memory."""

    models: list[RunningModel] = []


class OllamaEngine(BaseInferenceEngine):
    """A local Ollama server."""

    NAME = "ollama"
    LABEL = "Ollama"
    DEFAULT_URL = "http://localhost:11434"
    START = "ollama serve"
    ADD_MODEL = "ollama pull <model>"

    async def _version(self, client: httpx.AsyncClient) -> str | None:
        try:
            return (await self._get(client, "/api/version"))["version"]
        except Exception as e:
            logger.debug(f"Failed to fetch Ollama version: {e}")
            return None

    async def fetch_models(self) -> list[InferenceModel]:
        async with self._client() as client:
            return _Tags.model_validate(await self._get(client, "/api/tags")).models

    async def _holds(self, client: httpx.AsyncClient, model: str) -> bool:
        """``/api/ps`` alone: the models in memory."""
        running = _Ps.model_validate(await self._get(client, "/api/ps")).models
        return any(model in (m.name, m.model) for m in running)

    async def _move(self, action: str, model_name: str) -> None:
        """An empty ``/api/generate``: loads the model and keeps it 30
        minutes, or (``keep_alive`` 0) frees it now; generates nothing."""
        loading = action == "load"
        await self._post(
            "/api/generate",
            {"model": model_name, "prompt": "", "keep_alive": "30m" if loading else 0},
            60.0 if loading else 30.0,
        )

    async def get_server_status(self) -> InferenceServerStatus:
        """In one connection: the installed models' ``/api/tags`` also
        answers whether the server is there (a failed read is
        "unavailable"), then the version and the running models together."""
        async with self._client() as client:
            try:
                tags = await self._get(client, "/api/tags")
            except (httpx.HTTPError, ValueError):
                return InferenceServerStatus(available=False)
            version, ps = await asyncio.gather(
                self._version(client), self._get(client, "/api/ps")
            )
        running_models = _Ps.model_validate(ps).models
        return InferenceServerStatus(
            available=True,
            version=version,
            running_models=running_models,
            installed_models=_Tags.model_validate(tags).models,
            total_vram_gb=round(sum(m.size_vram_gb for m in running_models), 2),
        )
