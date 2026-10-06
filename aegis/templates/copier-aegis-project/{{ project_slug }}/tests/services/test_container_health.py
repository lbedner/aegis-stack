"""A component's health is the worse of its own check and Docker's
healthcheck on its containers, as the containers sampler last read them
(``container_health``)."""

import pytest

from app.core import series
from app.services.system import container_health, health, ui_runtime
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._fake_runtime import REDIS, UNHEALTHY, FakeRuntime, use_runtime


def _checks(status: ComponentStatusType = ComponentStatusType.HEALTHY) -> dict:
    return {
        "ingress": ComponentStatus(
            name="ingress", status=status, message="Traefik active"
        ),
        "cache": ComponentStatus(name="cache", message="Connected"),
    }


async def _sampled(monkeypatch: pytest.MonkeyPatch, *instances: object) -> None:
    use_runtime(monkeypatch, FakeRuntime(*instances))
    await series.sample(ui_runtime.CONTAINERS)


async def test_a_passing_check_with_a_failing_healthcheck_is_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _sampled(monkeypatch, REDIS, UNHEALTHY)
    found = await container_health.overlay(_checks())
    assert found["ingress"].status == ComponentStatusType.WARNING
    assert UNHEALTHY.name in found["ingress"].message
    assert found["cache"].status == ComponentStatusType.HEALTHY


async def test_a_failing_check_keeps_its_status_and_its_own_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _sampled(monkeypatch, UNHEALTHY)
    found = await container_health.overlay(_checks(ComponentStatusType.UNHEALTHY))
    assert found["ingress"].status == ComponentStatusType.UNHEALTHY
    assert found["ingress"].message == "Traefik active"


async def test_before_the_containers_are_read_nothing_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Docker call of its own: the health walk waits on nothing."""
    fake = FakeRuntime(UNHEALTHY)
    use_runtime(monkeypatch, fake)
    checks = _checks()
    assert await container_health.overlay(checks) == checks
    assert fake.listed == 0


async def test_the_system_status_carries_it(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ingress() -> ComponentStatus:
        return _checks()["ingress"]

    monkeypatch.setattr(health, "_health_checks", {"ingress": ingress})
    monkeypatch.setattr(health, "_service_health_checks", {})
    await _sampled(monkeypatch, UNHEALTHY)
    status = await health.get_system_status(force_refresh=True)
    components = status.components["aegis"].sub_components["components"]
    assert components.sub_components["ingress"].status == ComponentStatusType.WARNING
