"""Local model serving: the engine behind one interface (``engine``), its
activity tracker, and the sampler that reads it."""

from app.components.inference.engine import BaseInferenceEngine
from app.components.inference.ollama import OllamaEngine

# Engines by their ``inference[<engine>]`` name.
ENGINES: dict[str, type[BaseInferenceEngine]] = {"ollama": OllamaEngine}


def get_inference_engine() -> BaseInferenceEngine:
    """This app's inference engine, at its configured URL."""
    return ENGINES["ollama"]()
