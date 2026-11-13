"""The inference samplers (``app.core.series``): Ollama read once a tick for
every viewer, rather than once a second by each. Each loaded model's memory
and VRAM for the charts, and the server as a whole for the Inference page
and the Flet Ollama modal (``current_status``). It is also the one reader
that notices models loading and leaving (``get_inference_activity``): Ollama
has no event API, so each reading's running set is diffed with the last.

The speech server is read the same way (``SPEECH``) for Inference > Speech.
"""

import httpx

from app.components.inference import get_inference_engine
from app.components.inference.activity import get_inference_activity
from app.components.inference.engine import InferenceServerStatus
from app.core import series, speech_server
from app.core.log import logger
from app.core.series import Sample, Sampler
from app.services.system.models import ComponentStatus
from app.services.system.ui_runtime import Chart, Host


async def read() -> Sample:
    """The server now: ``latest`` is it with where it was looked for."""
    client = get_inference_engine()
    server = await client.get_server_status()
    if server.available:
        get_inference_activity().observe(
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


REQUESTS = "requests"


async def read_speech() -> Sample:
    """The speech server now (``app.core.speech_server``): its process's
    memory and its requests in flight for the charts, where it reports them,
    and the reading whole for the Speech section; nothing where none is
    set."""
    from app.core.config import settings

    url = speech_server.reach(settings)
    if url is None:
        return Sample({}, None)
    reading = await speech_server.read(url)
    found = {series.MEMORY: reading.memory_bytes, REQUESTS: reading.active_requests}
    values = {
        f"{speech_server.NAME}:{metric}": float(value)
        for metric, value in found.items()
        if value is not None
    }
    return Sample(values, reading)


SPEECH = Sampler(speech_server.SAMPLER, read_speech)
SPEECH_CHARTS = (
    Chart(
        "memory",
        "Memory",
        f"{speech_server.SAMPLER}:",
        series.MEMORY,
        "bytes",
        empty="Nothing reported in {window}: it reports its memory with "
        f"{speech_server.DEBUG}=true.",
    ),
    Chart(
        "requests",
        "Requests in flight",
        f"{speech_server.SAMPLER}:",
        REQUESTS,
        empty="Nothing reported in {window}: it reports its requests with "
        f"{speech_server.DEV}=true.",
    ),
    Chart(
        "latency",
        "Latency",
        f"{speech_server.CALLS}:",
        series.LATENCY,
        "seconds",
        empty="No line said in {window}: a whole file, or a stream until its "
        "first audio.",
        style="events",
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
            InferenceServerStatus(available=False), get_inference_engine().base_url
        )
    return ollama_status(server, url)
