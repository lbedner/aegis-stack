"""The host checks (``health_probes``): CPU is psutil's share since its
previous read in this process, so two reads moments apart would make the
second one read idle. The cached readings are taken once however many ask
at once (the health walk and Overseer's host sampler, say)."""

import asyncio

import pytest

from app.services.system import health_probes


async def test_readers_at_once_share_one_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[float] = []

    def cpu_percent(_: object) -> float:
        reads.append(62.5)
        return 62.5

    monkeypatch.setattr(health_probes.psutil, "cpu_percent", cpu_percent)
    health_probes._system_metrics_cache.clear()
    first, again = await asyncio.gather(
        health_probes.host_metrics(), health_probes.host_metrics()
    )
    assert len(reads) == 1
    assert first["cpu"].metadata["percent_used"] == 62.5
    assert again["cpu"].metadata["percent_used"] == 62.5
