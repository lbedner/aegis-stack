"""The service standard, held by the parts pattern's report
(``service_parts.PARTS``): every enforced rule at zero breaches, but for
the reads outside queries modules recorded below as debt.

Behavioural tests cannot see structure: a read that drifts out of its
package's ``queries`` module still returns the same rows. This is where
the standard fails on the drift. Likewise a subsystem left loose beside
a service's standard files instead of in a package under ``domains/``.
"""

from app.core import ownership, source_index
from app.services.system import pattern_findings, service_parts

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

# Files outside a service that import its internals (``service_parts.
# INTERNALS``) rather than its facade. The parts rule holds a service's own
# folder; this holds everything else (components, the CLI, core, shared
# code), the same ratchet: a file may only leave the list.
REACHING_DEBT = frozenset(
    {
        "app/cli/payment_e2e.py",
        "app/components/frontend/dashboard/modals/documents_activity.py",
        "app/components/frontend/dashboard/modals/documents_detail_pane.py",
        "app/components/frontend/dashboard/modals/documents_modal.py",
        "app/components/frontend/dashboard/modals/insights_modal/base.py",
        "app/components/frontend/dashboard/modals/meetings_calendar_tab.py",
        "app/components/frontend/dashboard/modals/meetings_modal.py",
        "app/components/frontend/dashboard/modals/meetings_search_tab.py",
        "app/components/frontend/dashboard/modals/meetings_threads.py",
        "app/components/web_frontend/meeting_agents.py",
        "app/components/web_frontend/meeting_calendar.py",
        "app/components/web_frontend/meeting_status.py",
        "app/components/web_frontend/overseer_meeting_search.py",
        "app/components/web_frontend/routes/meetings.py",
        "app/components/web_frontend/routes/partials/overseer_documents.py",
        "app/components/web_frontend/routes/partials/overseer_meetings.py",
        "app/components/worker/queues/system.py",
        "app/components/worker/tasks/document_tasks.py",
    }
)


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


def _service_of_internal(target: str, index: source_index.Index) -> str | None:
    """The service whose internals ``target`` (a dotted module or name) is,
    else None."""
    words = target.split(".")
    if words[:2] != ["app", "services"] or len(words) < 4:
        return None
    if words[3] not in service_parts.INTERNALS:
        return None
    found = ownership.owner(target, index)
    return found.name if found and found.kind == ownership.SERVICE else None


def test_no_caller_outside_a_service_reaches_past_its_facade() -> None:
    index = source_index.project()
    reaching = set()
    for name in index.paths:
        module = index.get(name) if name.startswith("app.") else None
        if module is None:
            continue
        mine = ownership.owner(name, index)
        for source, member in module.imported.values():
            target = f"{source}.{member}" if member else source
            theirs = _service_of_internal(target, index)
            if theirs and (mine is None or mine.name != theirs):
                reaching.add(module.path)
    assert reaching <= REACHING_DEBT, sorted(reaching - REACHING_DEBT)
