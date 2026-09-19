"""The zuvloop minimum Python version is stated twice. They must agree.

One statement is a PEP 508 marker in ``pyproject.toml.jinja``, which
decides whether the package installs. The other is ``ZUVLOOP_MIN_PYTHON``
in ``app/core/loops.py``, which decides whether selecting the loop is
refused at startup. They are in different files and different languages,
so they cannot share a definition, but they can be made to fail loudly
when they drift.

Drift is silent and asymmetric otherwise: raise the marker and the runtime
guard still waves through a version that no longer has a wheel; raise the
guard and a supported version is refused for no reason.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = (
    Path(__file__).parent.parent.parent
    / "aegis/templates/copier-aegis-project/{{ project_slug }}"
)


def _marker_version() -> tuple[int, ...]:
    """The floor in the dependency marker, e.g. (3, 14)."""
    pyproject = (TEMPLATE / "pyproject.toml.jinja").read_text()
    match = re.search(
        r'"zuvloop[^"]*;\s*python_version\s*>=\s*\'([\d.]+)\'"', pyproject
    )
    assert match, "no zuvloop dependency with a python_version marker"
    return tuple(int(part) for part in match.group(1).split("."))


def _guard_version() -> tuple[int, ...]:
    """The floor the runtime guard enforces."""
    loops = (TEMPLATE / "app/core/loops.py").read_text()
    match = re.search(r"ZUVLOOP_MIN_PYTHON\s*=\s*\(([\d,\s]+)\)", loops)
    assert match, "no ZUVLOOP_MIN_PYTHON in app/core/loops.py"
    return tuple(int(part) for part in match.group(1).split(",") if part.strip())


def test_the_marker_and_the_runtime_guard_agree() -> None:
    marker, guard = _marker_version(), _guard_version()

    assert marker == guard, (
        f"zuvloop's install floor is {marker} but the runtime guard "
        f"enforces {guard}. Change both, or one of them is a lie."
    )
