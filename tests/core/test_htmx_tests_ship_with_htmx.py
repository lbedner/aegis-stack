"""A test for the htmx Overseer page ships only to a project that has htmx.

The worker and scheduler listed their Overseer page tests as primary files,
so ``aegis add scheduler`` on a project without htmx copied in
``tests/web/test_overseer_scheduler.py``, which imports
``app.components.web_frontend`` and broke the project's test collection.
Services already gate theirs on ``include_htmx``; every spec does now, and
the scheduler's add path honours the same gates as everyone else's.
"""

from __future__ import annotations

import pytest

from aegis.core.component_files import get_component_files
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES

SPECS = sorted(name for name in {**COMPONENTS, **SERVICES} if name != "htmx")


@pytest.mark.parametrize("name", SPECS)
def test_no_htmx_test_ships_without_htmx(name: str) -> None:
    added = get_component_files(name, answers={"include_htmx": False})
    assert not [p for p in added if p.startswith("tests/web/")]


@pytest.mark.parametrize("name", ["scheduler", "worker"])
def test_the_page_test_still_ships_with_the_overseer(name: str) -> None:
    """The Overseer pages are auth's (its ``include_htmx`` group), so a page
    test needs htmx and auth beside the component it tests."""
    added = get_component_files(
        name, answers={"include_htmx": True, "include_auth": True}
    )
    assert f"tests/web/test_overseer_{name}.py" in added


@pytest.mark.parametrize("name", ["scheduler", "worker"])
def test_removing_the_spec_still_takes_its_page_test(name: str) -> None:
    assert f"tests/web/test_overseer_{name}.py" in get_component_files(name, full=True)
