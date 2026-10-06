"""What each part of the app costs the webserver to load (``load_cost``):
each one loaded alone in a fresh Python on top of the app's core, measured
by one process of many in the background, kept per build."""

from uuid import uuid4

import pytest

from app.core.config import settings
from app.services.system import load_cost
from app.services.system.models import LoadCosts, LoadReading

# The real one: tests at large never start measuring (``conftest``).
START = load_cost._start


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each part's load as ``(core, core + 10 MB per letter of its name)``,
    and the modules asked for, in order."""
    asked: list[str] = []

    async def load(module: str, under: list[str]) -> LoadReading:
        asked.append(module)
        name = module.rsplit(".", 1)[-1]
        if name == "broken":
            raise load_cost.LoadError(f"{module} would not import")
        return LoadReading(before=100, after=100 + len(name) * 10_000_000)

    # A build of its own: the cache keeps a build's measurement.
    monkeypatch.setattr(settings, "BUILD_ID", f"test-{uuid4().hex}")
    monkeypatch.setattr(load_cost, "_load", load)
    monkeypatch.setattr(load_cost, "_start", START)
    monkeypatch.setattr(
        load_cost,
        "parts",
        lambda: {
            "service_ai": "app.services.ai",
            "web_frontend": "app.components.web_frontend",
            "service_broken": "app.services.broken",
        },
    )
    return asked


async def test_each_part_is_measured_alone_on_top_of_the_core(
    loads: list[str],
) -> None:
    await load_cost.measure()
    assert await load_cost.costs() == LoadCosts(
        core=100, parts={"service_ai": 20_000_000, "web_frontend": 120_000_000}
    )
    assert loads == [
        "app.services.ai",
        "app.components.web_frontend",
        "app.services.broken",
    ]


async def test_until_it_is_measured_it_says_so_and_measures_once(
    loads: list[str],
) -> None:
    """The first look starts it; looks while it runs wait on the same one."""
    assert await load_cost.costs() is None
    assert await load_cost.costs() is None
    assert load_cost._task is not None
    await load_cost._task
    assert loads.count("app.services.ai") == 1
    assert (await load_cost.costs()).parts["service_ai"] == 20_000_000


async def test_one_process_of_many_measures(loads: list[str]) -> None:
    """The claim: another process, or this one again after a failed run,
    leaves it to the holder."""
    await load_cost.measure()
    await load_cost.measure()
    assert loads.count("app.services.ai") == 1


async def test_a_change_to_how_it_measures_measures_again(
    loads: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kept per build and per way of measuring: a development build is
    always ``dev``, so a new way would otherwise show the old one's."""
    await load_cost.measure()
    assert await load_cost.costs() is not None
    monkeypatch.setattr(load_cost, "_METHOD", "changed")
    assert await load_cost.costs() is None


async def test_a_module_is_loaded_in_a_fresh_python() -> None:
    """Its memory in use before and after, from a Python of its own."""
    read = await load_cost._load("decimal", ["json"])
    assert 0 < read.before <= read.after


def test_every_service_and_the_webservers_components_are_measured() -> None:
    """Keyed as the name registry keys them; the worker's and the
    scheduler's entry points are their own processes'."""
    found = load_cost.parts()
    assert found["service_system"] == "app.services.system"
    assert found["backend"] == "app.components.backend"
    assert not load_cost.OWN_PROCESS & set(found)


def test_a_part_is_measured_on_top_of_the_parts_it_uses() -> None:
    """The web frontend's Overseer pages import every service: loaded
    alone it would count them all again. On top of what it uses, it is its
    own code and libraries. A part that imports it back (the server's
    routes import every service, and AI imports the server) is not used:
    loading it first would load this part too."""
    imported = {
        "app.services.ai": {"app.components.backend.api.deps", "pydantic_ai"},
        "app.components.backend": {"app.services.ai.router"},
        "app.components.web_frontend": {"app.services.ai.service", "jinja2"},
    }
    assert load_cost.uses("app.components.web_frontend", imported) == [
        "app.services.ai"
    ]
    assert load_cost.uses("app.services.ai", imported) == []


def test_the_way_of_measuring_covers_which_parts_count_as_used() -> None:
    """The cache keeps a build's measurement, and a development build is
    always ``dev``: the key's fingerprint covers the script and the rule
    for what a part is measured on top of, or a change to that rule shows
    the old rule's figures for a day."""
    import hashlib
    import inspect

    method = load_cost._SCRIPT + inspect.getsource(load_cost.uses)
    expected = hashlib.sha1(method.encode(), usedforsecurity=False).hexdigest()[:8]
    assert load_cost._METHOD == expected
