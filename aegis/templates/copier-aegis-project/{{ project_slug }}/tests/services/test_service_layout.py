"""The service standard, held by the parts pattern's report
(``service_parts.PARTS``): every enforced rule at zero breaches, but for
the reads outside queries modules recorded below as debt.

Behavioural tests cannot see structure: a read that drifts out of its
package's ``queries`` module still returns the same rows. This is where
the standard fails on the drift. Likewise a subsystem left loose beside
a service's standard files instead of in a package under ``domains/``.
"""

from app.services.system import pattern_findings, service_parts

READS = "parts.reads-in-queries"
# Files each part still reads in outside its queries modules: a ratchet,
# like ``test_module_size_budget.BUDGET``. A count may only drop, and a
# part not listed is held at zero; lower an entry as its reads move.
READS_DEBT = {
    "service:auth": 11,  # sessions' devices split from tokens' file
    "service:blog": 4,
    "service:documents": 1,
    "service:meetings": 1,  # landed after the domains move; ON-15
    "service:payment": 7,  # the invoice webhooks split from billing's file
    "service:research": 2,
    "component:scheduler": 3,
}
LOOSE = "parts.domains"
# Modules each service still keeps loose beside its standard files, held
# the same way: lower an entry as its modules move into domains/.
LOOSE_DEBT = {
    "service:research": 1,  # registry: the plugin entry point
    "service:meetings": 6,  # landed after the domains move; ON-15
}


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
