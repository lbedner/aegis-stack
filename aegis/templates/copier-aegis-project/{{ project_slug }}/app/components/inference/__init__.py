"""Local model serving: the engine behind one interface (``engine``), its
activity tracker, and the sampler that reads it."""

from app.components.inference.engine import BaseInferenceEngine
from app.components.inference.llamacpp import LlamaCppEngine
from app.components.inference.ollama import OllamaEngine

# Engines by their ``inference[<engine>]`` name.
ENGINES: dict[str, type[BaseInferenceEngine]] = {
    e.NAME: e for e in (OllamaEngine, LlamaCppEngine)
}


def inference_engine_class(name: str | None = None) -> type[BaseInferenceEngine]:
    """This app's inference engine, or the one called ``name`` (each local
    AI provider is named as its engine is): what it is, without reaching it."""
    from app.core.config import settings

    return ENGINES[name or settings.INFERENCE_ENGINE]


def get_inference_engine(name: str | None = None) -> BaseInferenceEngine:
    """``inference_engine_class``'s engine, at its configured URL."""
    return inference_engine_class(name)()
