"""The service standard, held by the parts pattern's report
(``service_parts.PARTS``): every enforced rule at zero breaches, but for
the reads outside queries modules recorded below as debt.

Behavioural tests cannot see structure: a read that drifts out of its
package's ``queries`` module still returns the same rows. This is where
the standard fails on the drift. Likewise a subsystem left loose beside
a service's standard files instead of in a package under ``domains/``.
"""

import importlib
import importlib.util

from fastapi import FastAPI

from app.core import source_index
from app.services.system import pattern_findings, patterns, service_parts
from tests._conformance import CONFORMANCE

pytestmark = CONFORMANCE

READS = "parts.reads-in-queries"
# Files each part still reads in outside its queries modules: a ratchet,
# like ``test_module_size_budget.BUDGET``. A count may only drop, and a
# part not listed is held at zero; lower an entry as its reads move.
READS_DEBT = {
    "service:auth": 11,  # sessions' devices split from tokens' file
    "service:blog": 4,
    "service:documents": 1,
    "service:payment": 7,  # the invoice webhooks split from billing's file
    "service:research": 2,
    "component:scheduler": 3,
}
LOOSE = "parts.domains"
# Modules each service still keeps loose beside its standard files, held
# the same way: lower an entry as its modules move into domains/.
LOOSE_DEBT: dict[str, int] = {}


def _findings() -> list[pattern_findings.Finding]:
    return pattern_findings.findings(service_parts.report())


def _errors() -> list[pattern_findings.Finding]:
    return [f for f in _findings() if f.severity == "error"]


def _past(check: str, debt: dict[str, int]) -> dict[str, list[str]]:
    """The files each subject breaks ``check`` in, where past its debt."""
    files = {f.subject: sorted(set(f.files)) for f in _findings() if f.check == check}
    return {s: found for s, found in files.items() if len(found) > debt.get(s, 0)}


def test_reads_outside_queries_never_grow() -> None:
    over = _past(READS, READS_DEBT)
    assert not over, f"reads outside queries modules, past the debt: {over}"


def test_loose_modules_never_grow() -> None:
    over = _past(LOOSE, LOOSE_DEBT)
    assert not over, f"modules left loose beside the standard, past the debt: {over}"


def test_every_other_enforced_rule_holds() -> None:
    broken = [(f.check, f.subject, f.evidence) for f in _errors() if f.check != READS]
    assert not broken, broken


def _resolves(source: str, member: str) -> bool:
    """``member`` is a name ``source`` offers, or a submodule of it."""
    if hasattr(importlib.import_module(source), member):
        return True
    try:
        return importlib.util.find_spec(f"{source}.{member}") is not None
    except ModuleNotFoundError:  # a facade that is a module, not a package
        return False


def test_every_name_taken_from_a_facade_is_one_it_offers() -> None:
    """A facade loads its names lazily (``facade.lazy``), and the type
    checker takes any name from its ``__getattr__``: a name missing from
    its ``TYPE_CHECKING`` list fails only when the import runs - in a
    worker, mid-job. Every name the project imports from one, and its
    service defines, must load. A name the stack's service lacks (an
    option it was built without) is a task that never runs here."""
    index = source_index.project()

    def defined(service: str, member: str) -> bool:
        return any(
            (module := index.get(name)) and member in module.defined
            for name in index.paths
            if name.startswith(f"{service}.")
        )

    facades = {
        name
        for name in index.paths
        if (module := index.get(name))
        and any("facade.lazy(" in line for line in module.lines)
    }
    missing = set()
    for name in index.paths:
        module = index.get(name)
        if module is None:
            continue
        for full in module.imports:
            source, _, member = full.rpartition(".")
            service = ".".join(source.split(".")[:3])
            if (
                source in facades
                and not _resolves(source, member)
                and defined(service, member)
            ):
                missing.add(f"{module.path}: {full}")
    assert not missing, sorted(missing)


def test_the_shipped_app_breaks_no_enforced_route_rule(app: FastAPI) -> None:
    report = patterns.report(patterns.ROUTE, app.routes)
    broken = {r.key: [i.label for i in r.violations] for r in report.enforced}
    assert not any(broken.values()), broken
