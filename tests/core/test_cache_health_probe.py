"""Concurrent health checks must not fail each other (#416).

Redis reported "Redis set/get test failed" in Overseer while Redis was
fine. The probe wrote, read and deleted one fixed key, and the check does
not run alone: every webserver replica, the scheduler, the workers and the
dashboard poll it against one shared database. Two of them overlapping is
enough for one to read the other's value, or to read nothing because the
other already deleted the key.
"""

from __future__ import annotations

import re

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _rendered() -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    return env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/app/services/system/health_cache.py.jinja"
    ).render({**get_copier_defaults(), "project_slug": "demo", "include_redis": True})


def test_the_probe_key_is_not_a_constant() -> None:
    """A constant key is the whole bug: two checkers share one slot, so one
    reads the other's value or finds it already deleted."""
    source = _rendered()

    constant_key = re.search(r'test_key = "[^"]*"', source)
    assert constant_key is None, constant_key.group(0) if constant_key else ""


def test_a_value_that_came_back_missing_is_compared_not_dereferenced() -> None:
    """``retrieved_value.decode()`` raised AttributeError when the key was
    gone, so a healthy Redis failed its check with an unrelated message."""
    source = _rendered()

    assert "retrieved_value.decode() != test_value" not in source
