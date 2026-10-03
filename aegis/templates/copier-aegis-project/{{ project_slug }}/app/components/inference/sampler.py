"""The inference sampler (``app.core.series``): Ollama read once a tick for
every viewer, rather than once a second by each. Each loaded model's memory
and VRAM for the charts, and the server as a whole for the Inference page.
"""

from app.components.inference.ollama import OllamaClient
from app.core import series
from app.core.series import Sample, Sampler


async def read() -> Sample:
    """The server now: ``latest`` is it with where it was looked for."""
    client = OllamaClient()
    server = await client.get_server_status()
    values: dict[str, float] = {}
    for model in server.running_models:
        values[f"{model.name}:{series.MEMORY}"] = model.size
        values[f"{model.name}:{series.VRAM}"] = model.size_vram
    return Sample(values, (server, client.base_url))


SAMPLER = Sampler(series.INFERENCE, read)
