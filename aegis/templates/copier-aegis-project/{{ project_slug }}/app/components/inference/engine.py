"""One interface over the local inference engines (``inference[<engine>]``).

Callers get an engine from ``get_inference_engine`` (this package) and never
import an engine class. What it reports comes back in the neutral shapes
below; a fact an engine does not report keeps its empty default, and the
pages leave it out.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from app.components.inference.activity import get_inference_activity
from app.core.log import logger

# What a caller may ask of a model: warm it into memory, or free it.
MODEL_ACTIONS = ("load", "unload")


class ModelDetails(BaseModel):
    """What a model is, as far as its engine reports it."""

    model_config = ConfigDict(extra="ignore")

    parent_model: str = ""
    format: str = ""  # e.g., "gguf"
    family: str = ""  # e.g., "qwen2", "llama"
    families: list[str] = []  # e.g., ["qwen2"]
    parameter_size: str = ""  # e.g., "7.6B", "14.8B"
    quantization_level: str = ""  # e.g., "Q4_K_M", "Q8_0"
    # Two models at the same parameter count are very different machines
    # if one holds 256K tokens and the other 4K; known WITHOUT loading it.
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


class InferenceModel(BaseModel):
    """A model the engine has on disk."""

    model_config = ConfigDict(extra="ignore")

    name: str  # e.g., "qwen2.5:7b"
    model: str  # Same as name
    size: int  # bytes on disk
    digest: str = ""
    modified_at: datetime | None = None
    details: ModelDetails = ModelDetails()
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


class RunningModel(BaseModel):
    """A model the engine holds in memory."""

    model_config = ConfigDict(extra="ignore")

    name: str
    model: str
    size: int  # bytes
    size_vram: int = 0  # bytes of VRAM it holds
    digest: str = ""
    details: ModelDetails = ModelDetails()
    expires_at: datetime | None = None  # when it unloads if idle
    context_length: int = 0  # the context it serves

    @computed_field
    @property
    def size_vram_gb(self) -> float:
        """Get VRAM usage in gigabytes."""
        return round(self.size_vram / (1024**3), 2)

    @computed_field
    @property
    def is_warm(self) -> bool:
        """Loaded and ready: a running model is warm."""
        return True


class InferenceServerStatus(BaseModel):
    """The engine's server in one reading."""

    available: bool  # Server is reachable
    version: str | None = None
    running_models: list[RunningModel] = []
    installed_models: list[InferenceModel] = []
    total_vram_gb: float = 0.0

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


class BaseInferenceEngine(ABC):
    """A local inference server, read and driven over HTTP."""

    TIMEOUT = 2.0  # Local server responds in <100ms; 2s is generous

    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """``base_url`` defaults to the configured effective URL, which
        resolves ``localhost`` to ``host.docker.internal`` in a container -
        without it a containerized caller dials its own loopback and
        concludes the engine is not installed."""
        self.base_url = str(base_url or self.configured_url()).rstrip("/")
        self._transport = transport  # tests answer through a MockTransport

    @classmethod
    @abstractmethod
    def configured_url(cls) -> str:
        """Where the settings say the server is."""

    def _client(self, timeout: float = TIMEOUT) -> httpx.AsyncClient:
        """A client for one call or one status read (shared by its reads)."""
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def _get(self, client: httpx.AsyncClient, path: str) -> Any:
        """``path``'s JSON, or the HTTP error."""
        response = await client.get(f"{self.base_url}{path}")
        response.raise_for_status()
        return response.json()

    @abstractmethod
    async def get_server_status(self) -> InferenceServerStatus:
        """The server now; unreachable is ``available=False``, not an error."""

    @abstractmethod
    async def fetch_models(self) -> list[InferenceModel]:
        """The models it has; raises the HTTP error when it is down."""

    @abstractmethod
    async def _move(self, action: str, model_name: str) -> bool:
        """Load or unload ``model_name`` on the server; False when it did not."""

    async def move(self, action: str, model_name: str) -> bool:
        """Load or unload ``model_name`` by name (``MODEL_ACTIONS``), so a
        button or a route can pass the action it was given straight through;
        a move that happened goes on the Activity tab."""
        if action not in MODEL_ACTIONS:
            raise ValueError(f"Unknown model action: {action}")
        if not await self._move(action, model_name):
            return False
        logger.info("inference.model_moved", action=action, model=model_name)
        activity = get_inference_activity()
        if action == "load":
            activity.record_loaded(model_name)
        else:
            activity.record_unloaded(model_name)
        return True
