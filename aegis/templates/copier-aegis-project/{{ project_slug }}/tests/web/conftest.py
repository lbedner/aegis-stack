"""Fixtures for the web frontend tests.

Every route is rendered two ways: a full page on a cold load and a bare
fragment when htmx asks for it. ``client`` (from the root conftest) covers
the first; ``hx`` covers the second by sending the ``HX-Request`` header
on every request. Both wrap the same ``app`` fixture, so a test module can
swap in a different app for both at once.
"""

from collections.abc import Callable, Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader
import pytest

from app.components.web_frontend.rendering import templates


@pytest.fixture
def hx(app: FastAPI) -> Generator[TestClient]:
    """A client whose every request carries ``HX-Request: true``."""
    with TestClient(app, headers={"HX-Request": "true"}) as test_client:
        yield test_client


@pytest.fixture
def add_template() -> Generator[Callable[[str, str], None]]:
    """Register a throwaway named template for the duration of one test.

    Lets a test exercise the real ``templates`` environment (globals,
    filters, loader) through a probe page without shipping test-only
    files under ``app/``. The original loader is restored afterwards.
    """
    env = templates.env
    original = env.loader
    added: dict[str, str] = {}
    env.loader = ChoiceLoader([DictLoader(added), original])  # type: ignore[list-item]

    def _add(name: str, source: str) -> None:
        added[name] = source
        if env.cache is not None:
            env.cache.clear()

    yield _add
    env.loader = original
