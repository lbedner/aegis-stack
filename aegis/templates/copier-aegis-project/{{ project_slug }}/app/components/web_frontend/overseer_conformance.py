"""What the parts pattern (``service_parts.PARTS``) found, on the map,
always: each part opened up in the Server (``mark``), or each piece of a
service opened up (``mark_pieces``), marked with what it should fix: how
many places, in the rule's tone, and on hover what to do and each place,
linked to its line, with what it says there. Its tone stays its health: a
finding is about the code, not how the part is doing."""

from functools import cache
from typing import Any, NamedTuple

from app.core import source_index
from app.services.system import pattern_findings, service_parts
from app.services.system.pattern_findings import Finding
from app.services.system.service_pieces import Piece

from .overseer_zoom import registry_of


class Conformance(NamedTuple):
    findings: dict[str, list[Finding]]  # by map key
    lacks: dict[str, list[str]]  # each checked part's missing parts, by map key


@cache
def conformance() -> Conformance:
    """The parts report (``service_parts.report``) by the map's keys."""
    report = service_parts.report()
    found: dict[str, list[Finding]] = {}
    for finding in pattern_findings.findings(report):
        found.setdefault(registry_of(finding.subject), []).append(finding)
    lacks: dict[str, list[str]] = {}
    for instance in report.instances:
        lacks.setdefault(registry_of(instance.label), []).extend(instance.missed)
    return Conformance(found, lacks)


def mark(stack: list[dict[str, Any]], found: Conformance) -> None:
    """Each checked part in ``stack``: every place its findings point at,
    and the parts it lacks."""
    for item in stack:
        key = item["registry"]
        if key in found.lacks:
            findings = found.findings.get(key, [])
            missing = found.lacks[key]
            note = f"Lacks: {', '.join(missing)}" if missing else None
            _mark(item, [(f, f.evidence) for f in findings], note)


def mark_pieces(
    stack: list[dict[str, Any]], found: Conformance, key: str, pieces: list[Piece]
) -> None:
    """A service opened up: each piece, the places in its own files the
    findings about the service (``key``) point at."""
    held = {path: piece.key for piece in pieces for path in piece.paths}
    findings = found.findings.get(key, [])
    keys = {piece.key for piece in pieces}
    for item in stack:
        if item["key"] in keys:
            mine = [
                (
                    f,
                    tuple(
                        e
                        for e in f.evidence
                        if held.get(pattern_findings.place(e)[0]) == item["key"]
                    ),
                )
                for f in findings
            ]
            _mark(item, [(f, places) for f, places in mine if places], None)


def _mark(
    item: dict[str, Any],
    findings: list[tuple[Finding, tuple[str, ...]]],
    note: str | None,
) -> None:
    if note:
        item["note"] = note
    if not findings:
        return
    index = source_index.project()
    item |= {
        "todo": [
            {
                "action": f.action,
                "tone": f.severity,
                "places": [_place(f, e, index) for e in places],
            }
            for f, places in findings
        ],
        "todo_count": sum(len(places) for _, places in findings),
        "todo_tone": "error"
        if any(f.severity == "error" for f, _ in findings)
        else "warn",
    }


def _place(
    finding: Finding, evidence: str, index: source_index.Index
) -> dict[str, Any]:
    path, line = pattern_findings.place(evidence)
    note = service_parts.place_note(finding.check, path, line, index)
    return {"path": path, "line": line, "note": note}
