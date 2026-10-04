"""
Ollama API client for health checks and model discovery.

Provides a lightweight client for interacting with local Ollama server.
This module is separate from ETL to ensure availability regardless of AI backend.
"""

import asyncio
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from app.components.inference.activity import get_ollama_activity
from app.core.log import logger

# Default Ollama server URL for local development
OLLAMA_DEFAULT_URL = "http://localhost:11434"
# What a caller may ask of a model: warm it into memory, or free it.
MODEL_ACTIONS = ("load", "unload")


class OllamaModelDetails(BaseModel):
    """Model details from Ollama API."""

    model_config = ConfigDict(extra="ignore")

    parent_model: str = ""
    format: str = ""  # e.g., "gguf"
    family: str = ""  # e.g., "qwen2", "llama"
    families: list[str] = []  # e.g., ["qwen2"]
    parameter_size: str = ""  # e.g., "7.6B", "14.8B"
    quantization_level: str = ""  # e.g., "Q4_K_M", "Q8_0"
    # Two models at the same parameter count are very different machines
    # if one holds 256K tokens and the other 4K. Ollama reports this on
    # /api/tags, so it is known WITHOUT loading the model.
    context_length: int = 0  # e.g., 262144
    embedding_length: int = 0  # e.g., 2048

    @field_validator("families", mode="before")
    @classmethod
    def normalize_families(cls, v: str | list[str] | None) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []


class OllamaModel(BaseModel):
    """Model data from Ollama's /api/tags endpoint."""

    model_config = ConfigDict(extra="ignore")

    name: str  # Model name (e.g., "qwen2.5:7b")
    model: str  # Same as name
    size: int  # Model size in bytes (on disk)
    digest: str  # Model digest/hash
    modified_at: datetime  # When model was last modified
    details: OllamaModelDetails
    # e.g., ["completion", "tools", "vision", "thinking"]. "tools" is the
    # one that decides whether a model can drive an agent at all - a model
    # without it cannot call anything, however good its prose is.
    capabilities: list[str] = []

    @computed_field
    @property
    def size_gb(self) -> float:
        """Get model size in gigabytes."""
        return round(self.size / (1024**3), 2)

    @computed_field
    @property
    def model_id(self) -> str:
        """Get model ID for catalog - keeps full name including tag."""
        return self.name


class OllamaRunningModel(BaseModel):
    """Model data from Ollama's /api/ps endpoint (running models)."""

    model_config = ConfigDict(extra="ignore")

    name: str  # Model name (e.g., "qwen2.5:7b")
    model: str  # Same as name
    size: int  # Model size in bytes
    size_vram: int  # VRAM currently used by this model
    digest: str  # Model digest/hash
    details: OllamaModelDetails
    expires_at: datetime  # When model will be unloaded if idle
    context_length: int = 0  # Context window size

    @computed_field
    @property
    def size_vram_gb(self) -> float:
        """Get VRAM usage in gigabytes."""
        return round(self.size_vram / (1024**3), 2)

    @computed_field
    @property
    def is_warm(self) -> bool:
        """Check if model is warm (loaded and ready)."""
        return True  # If it's in /api/ps, it's warm


class OllamaTagsResponse(BaseModel):
    """Response from /api/tags endpoint."""

    model_config = ConfigDict(extra="ignore")

    models: list[OllamaModel] = []


class OllamaPsResponse(BaseModel):
    """Response from /api/ps endpoint."""

    models: list[OllamaRunningModel] = []


class OllamaVersionResponse(BaseModel):
    """Response from /api/version endpoint."""

    version: str


class OllamaServerStatus(BaseModel):
    """Comprehensive status information from Ollama server."""

    available: bool  # Server is reachable
    version: str | None = None  # Server version
    running_models: list[OllamaRunningModel] = []  # Currently loaded models
    installed_models: list[OllamaModel] = []  # All installed models
    total_vram_gb: float = 0.0  # Total VRAM used by running models

    @computed_field
    @property
    def installed_models_count(self) -> int:
        """Get count of installed models."""
        return len(self.installed_models)

    @computed_field
    @property
    def running_models_count(self) -> int:
        """Get count of running models."""
        return len(self.running_models)


class OllamaClient:
    """Client for fetching model data from local Ollama server."""

    TIMEOUT = 2.0  # Local server responds in <100ms; 2s is generous

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Initialize the Ollama client.

        Args:
            base_url: Base URL for the Ollama server. Defaults to the
                configured effective URL, which resolves ``localhost`` to
                ``host.docker.internal`` when running in a container -
                without it a containerized caller dials its own loopback and
                concludes Ollama is not installed.
        """
        from app.core.config import settings

        resolved = base_url or getattr(
            settings, "ollama_base_url_effective", OLLAMA_DEFAULT_URL
        )
        self.base_url = str(resolved).rstrip("/")
        self._transport = transport  # tests answer through a MockTransport

    def _client(self, timeout: float = TIMEOUT) -> httpx.AsyncClient:
        """A client for one call or one status read (shared by its reads)."""
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def _get(self, client: httpx.AsyncClient, path: str) -> Any:
        """``path``'s JSON, or the HTTP error."""
        response = await client.get(f"{self.base_url}{path}")
        response.raise_for_status()
        return response.json()

    async def _version(self, client: httpx.AsyncClient) -> str | None:
        try:
            data = await self._get(client, "/api/version")
            return OllamaVersionResponse.model_validate(data).version
        except Exception as e:
            logger.debug(f"Failed to fetch Ollama version: {e}")
            return None

    async def fetch_models(self) -> list[OllamaModel]:
        """Fetch all installed models from Ollama.

        Returns:
            List of OllamaModel objects for locally installed models.

        Raises:
            httpx.HTTPError: If the request fails.
            httpx.ConnectError: If Ollama server is not running.
        """
        try:
            async with self._client() as client:
                data = OllamaTagsResponse.model_validate(
                    await self._get(client, "/api/tags")
                )
                logger.debug(f"Fetched {len(data.models)} models from Ollama")
                return data.models
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Ollama at {self.base_url}: {e}")
            raise

    async def is_available(self) -> bool:
        """Check if Ollama server is running and accessible.

        Returns:
            True if Ollama is available, False otherwise.
        """
        try:
            async with self._client() as client:
                response = await client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    async def load_model(self, model_name: str, keep_alive: str = "30m") -> bool:
        """Load a model into VRAM (warm it up).

        Uses the /api/generate endpoint with an empty prompt to load
        the model into memory without generating text.

        Args:
            model_name: Name of the model to load (e.g., 'qwen2.5:7b')
            keep_alive: How long to keep the model in memory (default: '30m')

        Returns:
            True if model was loaded successfully, False otherwise.
        """
        url = f"{self.base_url}/api/generate"

        try:
            async with self._client(60.0) as client:
                response = await client.post(
                    url,
                    json={
                        "model": model_name,
                        "prompt": "",
                        "keep_alive": keep_alive,
                    },
                )
                response.raise_for_status()
                logger.info(f"Successfully loaded model: {model_name}")
                get_ollama_activity().record_loaded(model_name)
                return True
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Ollama at {self.base_url}: {e}")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to load model {model_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading model {model_name}: {e}")
            return False

    async def unload_model(self, model_name: str) -> bool:
        """Unload a model from VRAM (free up memory).

        Uses the /api/generate endpoint with keep_alive=0 to immediately
        unload the model from memory.

        Args:
            model_name: Name of the model to unload (e.g., 'qwen2.5:7b')

        Returns:
            True if model was unloaded successfully, False otherwise.
        """
        url = f"{self.base_url}/api/generate"

        try:
            async with self._client(30.0) as client:
                response = await client.post(
                    url,
                    json={
                        "model": model_name,
                        "prompt": "",
                        "keep_alive": 0,
                    },
                )
                response.raise_for_status()
                logger.info(f"Successfully unloaded model: {model_name}")
                get_ollama_activity().record_unloaded(model_name)
                return True
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Ollama at {self.base_url}: {e}")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to unload model {model_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error unloading model {model_name}: {e}")
            return False

    async def move(self, action: str, model_name: str) -> bool:
        """Load or unload ``model_name`` by name (``MODEL_ACTIONS``), so a
        button or a route can pass the action it was given straight through."""
        if action not in MODEL_ACTIONS:
            raise ValueError(f"Unknown model action: {action}")
        if action == "load":
            return await self.load_model(model_name)
        return await self.unload_model(model_name)

    async def get_server_status(self) -> OllamaServerStatus:
        """Get comprehensive Ollama server status, in one connection: the
        installed models' ``/api/tags`` also answers whether the server is
        there (a failed read is "unavailable"), then the version and the
        running models together.

        Returns:
            OllamaServerStatus with availability, running models, and metrics.
        """
        async with self._client() as client:
            try:
                tags = await self._get(client, "/api/tags")
            except (httpx.HTTPError, ValueError):
                return OllamaServerStatus(available=False)
            version, ps = await asyncio.gather(
                self._version(client), self._get(client, "/api/ps")
            )
        installed_models = OllamaTagsResponse.model_validate(tags).models
        running_models = OllamaPsResponse.model_validate(ps).models

        # Calculate total VRAM usage
        total_vram_gb = sum(m.size_vram_gb for m in running_models)

        return OllamaServerStatus(
            available=True,
            version=version,
            running_models=running_models,
            installed_models=installed_models,
            total_vram_gb=round(total_vram_gb, 2),
        )
