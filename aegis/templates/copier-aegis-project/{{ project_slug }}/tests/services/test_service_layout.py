"""The service layout rules every conformant service is held to.

Behavioural tests cannot see structure: a read that drifts out of its
package's ``queries`` module still returns the same rows. These
assertions are where the standard is stated, so they fail on the drift.
"""

from __future__ import annotations

import pathlib

import pytest

CONFORMANT_SERVICES = ("ai", "comms", "finance", "insights", "rag")

# One-shot loaders, not runtime code: exempt by decision, whether a
# folder or a single module.
EXEMPT = {"seed", "seeds", "demo_seed", "fixtures"}


@pytest.mark.parametrize("service", CONFORMANT_SERVICES)
def test_every_read_lives_in_a_queries_module(service: str) -> None:
    """Reads belong to a package's ``queries`` module; domain modules own
    writes and orchestration. A ``.exec(`` anywhere else is a read the
    next N+1 audit cannot find."""
    package = pytest.importorskip(f"app.services.{service}")
    root = pathlib.Path(package.__file__).parent
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if ".exec(" in path.read_text()
        and path.name != "queries.py"
        and "queries" not in path.parent.name
        and not EXEMPT & set(path.with_suffix("").parts)
    ]
    assert not offenders, f"{service}: reads outside queries modules: {offenders}"
