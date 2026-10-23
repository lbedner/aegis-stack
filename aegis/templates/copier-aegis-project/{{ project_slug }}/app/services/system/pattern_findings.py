"""Every pattern's report as findings: one shape for whatever reads them
(Overseer's map, the ``patterns`` CLI). Each says which
rule (``check``), about which node of the system model (``subject``), how
bad (an enforced rule's breach is an error), why, where (``path:line``s)
and what to do; its ``fingerprint`` changes only when one of those does,
so a finding dismissed stays dismissed until its condition changes."""

from collections.abc import Callable
from functools import cache
import inspect
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.core import source_index
from app.core.ontology import current
from app.core.ontology.parts import node_of
from app.services.system.errors.fingerprint import digest
from app.services.system.patterns import Report, SourceText, source


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    check: str  # ``<pattern>.<rule>``: ``parts.has-health``
    subject: str  # a node id: ``service:blog``
    severity: Literal["error", "warn"]
    title: str
    why: str
    evidence: tuple[str, ...]  # ``path:line``, from the project's root
    action: str
    fingerprint: str
    gated: bool = False  # a new place blocks a change, its debt aside

    @property
    def blocking(self) -> bool:
        """Whether a new place breaking it blocks a change: an enforced
        rule's (an error), or a gated one's."""
        return self.severity == "error" or self.gated

    @property
    def files(self) -> tuple[str, ...]:
        """Each evidence entry's file, in order (one per place it shows)."""
        return tuple(place(e)[0] for e in self.evidence)


def place(evidence: str) -> tuple[str, int]:
    """One evidence entry, ``path:line``, as its file and line."""
    path, _, line = evidence.rpartition(":")
    return path, int(line)


def text_at(index: source_index.Index, path: str, line: int) -> str:
    """The text on ``path``'s ``line``, stripped; empty where ``index`` has
    no such module or line."""
    module = index.get(source_index.module_name(path))
    return module.place(line).text if module and 0 < line <= len(module.lines) else ""


def findings(report: Report) -> list[Finding]:
    """``report``'s broken rules, one finding per instance and rule."""
    pattern = report.pattern
    rules = {rule.key: rule for rule in pattern.rules}
    subject = pattern.subject or _owner(pattern.function)
    found = []
    for instance in report.instances:
        for key in instance.findings:
            rule = rules[key]
            target = instance.target
            evidence = tuple(
                rule.evidence(target)
                if rule.evidence
                else [_where(pattern.function(target))]
            )
            check, about = f"{pattern.key}.{key}", subject(target)
            found.append(
                Finding(
                    check=check,
                    subject=about,
                    severity="error" if rule.enforced else "warn",
                    gated=rule.gate,
                    title=rule.title,
                    why=rule.why,
                    evidence=evidence,
                    action=rule.action or rule.title,
                    fingerprint=_fingerprint(check, about, evidence),
                )
            )
    return found


def _where(found: Any) -> str:
    """``path:line`` of a function, or of source already read."""
    line = (
        found.line
        if isinstance(found, SourceText)
        else inspect.getsourcelines(found)[1]
    )
    return f"{source(found)[1]}:{line}"


def _owner(function: Callable[[Any], Any]) -> Callable[[Any], str]:
    """An instance as the node owning its function's module (the module's
    name where no part owns it); the model read once a report."""
    ids = cache(lambda: {n.id for n in current().nodes})

    def subject(target: Any) -> str:
        found = function(target)
        module = (
            source_index.module_name(found.path)
            if isinstance(found, SourceText)
            else inspect.unwrap(found).__module__
        )
        return node_of(module, source_index.project(), ids()) or module

    return subject


def _fingerprint(check: str, subject: str, evidence: tuple[str, ...]) -> str:
    return digest([check, subject, *evidence])[:16]
