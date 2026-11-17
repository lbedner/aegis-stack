"""One interface over the local inference engines (``inference[<engine>]``).

Callers get an engine from ``get_inference_engine`` (this package) and never
import an engine class. What it reports comes back in the neutral shapes
below; a fact an engine does not report keeps its empty default, and the
pages leave it out.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar

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
    # Whether it loads and frees models on request; a llama-server started
    # on one model offers neither (the pages hide the buttons).
    can_load_unload: bool = True

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
    NAME: ClassVar[str]  # its ``inference[<engine>]`` name, and its provider's
    LABEL: ClassVar[str]  # how its name reads to a person
    DEFAULT_URL: ClassVar[str]  # where it is when the settings do not say
    START: ClassVar[str]  # how a person starts it, for a page it does not answer
    ADD_MODEL: ClassVar[str]  # how a model gets onto it, for an empty model list

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
    def titled(cls, version: str | None) -> str:
        """Its label, with the version it reports: ``v`` before a release
        number (``Ollama v0.5.7``), a build as it is (``llama.cpp b6700``)."""
        if not version:
            return cls.LABEL
        return f"{cls.LABEL} {'v' if version[0].isdigit() else ''}{version}"

    @classmethod
    def configured_url(cls) -> str:
        """Where the settings say the server is: ``<NAME>_base_url_effective``,
        the setting the AI service's provider of the same name chats at
        (``provider_names.local_base_url``)."""
        from app.core.config import settings

        return getattr(settings, f"{cls.NAME}_base_url_effective", cls.DEFAULT_URL)

    def _client(self, timeout: float = TIMEOUT) -> httpx.AsyncClient:
        """A client for one call or one status read (shared by its reads)."""
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def _get(self, client: httpx.AsyncClient, path: str) -> Any:
        """``path``'s JSON, or the HTTP error."""
        response = await client.get(f"{self.base_url}{path}")
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, body: dict[str, Any], timeout: float) -> None:
        """POST ``body`` to ``path``, raising the HTTP error."""
        async with self._client(timeout) as client:
            response = await client.post(f"{self.base_url}{path}", json=body)
            response.raise_for_status()

    @abstractmethod
    async def get_server_status(self) -> InferenceServerStatus:
        """The server now; unreachable is ``available=False``, not an error."""

    @abstractmethod
    async def fetch_models(self) -> list[InferenceModel]:
        """The models it has; raises the HTTP error when it is down."""

    @abstractmethod
    async def _move(self, action: str, model_name: str) -> None:
        """Load or unload ``model_name`` on the server, raising when it
        did not (``move`` says so, once for every engine)."""

    @abstractmethod
    async def _holds(self, client: httpx.AsyncClient, model: str) -> bool:
        """Whether ``model`` is in memory, in one cheap read; raises the
        HTTP error when the server does not answer."""

    async def waiting_reason(self, model: str) -> str | None:
        """Why a turn on ``model`` has not answered yet, said as its state
        (the composer's chip already names the model): "loading" while it
        is not in memory, a wait that ends on its own; "thinking" once it is.
        None when the server does not answer. Asked while a turn is quiet,
        so one read (``_holds``), never the whole status."""
        try:
            async with self._client() as client:
                warm = await self._holds(client, model)
        except (httpx.HTTPError, ValueError):
            return None
        return "thinking" if warm else "loading"

    async def move(self, action: str, model_name: str) -> bool:
        """Load or unload ``model_name`` by name (``MODEL_ACTIONS``), so a
        button or a route can pass the action it was given straight through;
        a move that happened goes on the Activity tab."""
        if action not in MODEL_ACTIONS:
            raise ValueError(f"Unknown model action: {action}")
        try:
            await self._move(action, model_name)
        except Exception as e:
            logger.error(
                f"{self.LABEL} at {self.base_url} could not {action} {model_name}: {e}"
            )
            return False
        logger.info("inference.model_moved", action=action, model=model_name)
        activity = get_inference_activity()
        if action == "load":
            activity.record_loaded(model_name)
        else:
            activity.record_unloaded(model_name)
        return True
