"""The inference sampler (``app.core.series``): Ollama read once a tick for
every viewer, rather than once a second by each. Each loaded model's memory
and VRAM for the charts, and the server as a whole for the Inference page
and the Flet Ollama modal (``current_status``). It is also the one reader
that notices models loading and leaving (``get_ollama_activity``): Ollama
has no event API, so each reading's running set is diffed with the last.
"""

import httpx

from app.components.inference.activity import get_ollama_activity
from app.components.inference.ollama import OllamaClient, OllamaServerStatus
from app.core import series
from app.core.log import logger
from app.core.series import Sample, Sampler
from app.services.system.models import ComponentStatus
from app.services.system.ui_runtime import Chart, Host


async def read() -> Sample:
    """The server now: ``latest`` is it with where it was looked for."""
    client = OllamaClient()
    server = await client.get_server_status()
    if server.available:
        get_ollama_activity().observe(
            {m.name: m.size_vram_gb for m in server.running_models}
        )
    values: dict[str, float] = {}
    for model in server.running_models:
        values[f"{model.name}:{series.MEMORY}"] = model.size
        values[f"{model.name}:{series.VRAM}"] = model.size_vram
    return Sample(values, (server, client.base_url))


SAMPLER = Sampler(series.INFERENCE, read)

# The Inference page's Container section when Ollama runs on the host, not in
# a container (``ui_runtime.host_of``): what it holds in memory, and how fast
# it answers this app (each LLM call's ``series.record``).
HOST = Host(
    "Ollama runs on this machine, outside Docker: what it holds in "
    "memory, and how fast it answers this app.",
    (
        Chart(
            "model-memory",
            "Model memory",
            f"{series.INFERENCE}:",
            series.MEMORY,
            "bytes",
            empty="No model loaded in {window}.",
        ),
        Chart(
            "tokens",
            "Tokens per second",
            f"{series.LLM}:",
            series.TOKENS_PER_SECOND,
            within="model-memory",
            empty="No calls to a loaded model in {window}.",
            style="events",
        ),
        Chart(
            "latency",
            "Latency",
            f"{series.LLM}:",
            series.LATENCY,
            "seconds",
            within="model-memory",
            empty="No calls to a loaded model in {window}.",
            style="events",
        ),
    ),
)


async def current_status(*, fresh: bool = False) -> ComponentStatus:
    """The server as a health status: the sampler's reading, which the Flet
    modal shows while open instead of polling Ollama itself; ``fresh`` (right
    after the modal's own load or unload) reads it now."""
    from app.services.system.health_ollama import ollama_status

    try:
        server, url = (await read()).latest if fresh else await series.reading(SAMPLER)
    except httpx.HTTPError as exc:  # /api/ps failed after /api/tags answered
        logger.warning("ollama.status_read_failed", error=str(exc))
        return ollama_status(
            OllamaServerStatus(available=False), OllamaClient().base_url
        )
    return ollama_status(server, url)
