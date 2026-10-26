"""``patterns check``: the findings a change brings, against the known debt
in ``.patterns-baseline.json`` (``check``).

Each place a finding shows (one ``path:line`` of its evidence) is known by
its rule, its part, its file and the text on that line, not the line's
number: code added above known debt does not make it new. Illiana gives
the verdict, last: blocked when a new place breaks a rule that holds a
change (an enforced or a gated one, ``Finding.blocking``), else clear.
The exit code is 0 unless ``strict`` and blocked.
Under GitHub Actions each new place is a workflow command, which GitHub
shows on the pull request's diff; with ``GITHUB_STEP_SUMMARY`` set, what
the change touches and its new findings are written there too; with
``PATTERNS_FOUND`` set, the new places are written to that file as JSON,
each with the key the baseline knows it by, for a reviewer to place."""

from collections import Counter
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import NamedTuple

from app.core.source_index import Index
from app.services.system.errors.fingerprint import digest
from app.services.system.pattern_findings import Finding, place, text_at

BASELINE = ".patterns-baseline.json"


class Spot(NamedTuple):
    """One place a finding shows, and what it is known by."""

    finding: Finding
    path: str
    line: int
    key: str

    @property
    def at(self) -> str:
        """``path:line``."""
        return f"{self.path}:{self.line}"


def check(
    found: Iterable[Finding],
    index: Index,
    *,
    touched: str = "",
    strict: bool = False,
    update: bool = False,
    env: Mapping[str, str] | None = None,
) -> tuple[str, int]:
    """What to print and the exit code. ``update`` writes the baseline:
    every place when there is none, else only the known ones still there."""
    env, baseline = env or {}, index.root / BASELINE
    here, before = _spots(found, index), _known(index)
    if update:
        now = Counter(s.key for s in here)
        keep = now & before if baseline.exists() else now
        body = {"tool": "patterns", "known": sorted(keep.elements())}
        baseline.write_text(json.dumps(body, indent=2) + "\n")
        return f"{BASELINE}: {keep.total()} known", 0
    fresh = _new(here, before)
    blocked = sum(s.finding.blocking for s in fresh)
    lines = [
        _annotation(s) if env.get("GITHUB_ACTIONS") else f"{s.at}: {_line(s)}"
        for s in fresh
    ]
    lines.append(_verdict(blocked, len(fresh) - blocked, before.total()))
    if into := env.get("PATTERNS_FOUND"):
        _write_found(fresh, Path(into))
    if summary := env.get("GITHUB_STEP_SUMMARY"):
        rows = [f"- {_weight(s)} `{s.at}` {_line(s)}" for s in fresh]
        heading = f"### Illiana: {'blocked' if blocked else 'clear'}"
        with open(summary, "a") as out:
            head = [touched] if touched else []
            out.write("\n".join([*head, heading, "", *rows, ""]))
    return "\n".join(lines), int(strict and blocked > 0)


def _write_found(fresh: list[Spot], into: Path) -> None:
    """The new places as JSON: where, the rule and what it says, whether
    it blocks, and the key the baseline knows it by."""
    found = [
        {
            "path": s.path,
            "line": s.line,
            "check": s.finding.check,
            "subject": s.finding.subject,
            "title": s.finding.title,
            "why": s.finding.why,
            "action": s.finding.action,
            "blocking": s.finding.blocking,
            "key": s.key,
        }
        for s in fresh
    ]
    into.write_text(json.dumps({"found": found}, indent=2) + "\n")


def _weight(spot: Spot) -> str:
    return "**Blocks**" if spot.finding.blocking else "Advisory"


def _verdict(blocked: int, advisory: int, known: int) -> str:
    """Illiana's verdict on the new places, with the known debt beside it."""
    tail = f"{advisory} advisory; {known} known in {BASELINE}"
    if not blocked:
        return f"Illiana: clear. {tail}"
    return f"Illiana: blocked. {breaks(blocked)} a rule that holds a change; {tail}"


def breaks(blocked: int) -> str:
    """How many new places break a rule that holds a change, as said."""
    return "1 new place breaks" if blocked == 1 else f"{blocked} new places break"


def new_spots(found: Iterable[Finding], index: Index) -> list[Spot]:
    """The places ``found`` shows that the baseline does not know."""
    return _new(_spots(found, index), _known(index))


def _known(index: Index) -> Counter[str]:
    baseline = index.root / BASELINE
    return Counter(
        json.loads(baseline.read_text())["known"] if baseline.exists() else []
    )


def _spots(found: Iterable[Finding], index: Index) -> list[Spot]:
    placed = []
    for f in found:
        for path, line in map(place, f.evidence):
            text = digest([text_at(index, path, line)])[:12]
            placed.append(Spot(f, path, line, f"{f.check} {f.subject} {path} {text}"))
    return placed


def _new(here: list[Spot], before: Counter[str]) -> list[Spot]:
    left, fresh = Counter(before), []
    for spot in here:
        if left[spot.key]:
            left[spot.key] -= 1
        else:
            fresh.append(spot)
    return fresh


def _line(spot: Spot) -> str:
    f = spot.finding
    said = f.title if f.action == f.title else f"{f.title}: {f.action}"
    return f"{f.check} ({f.subject}) {said}"


def _annotation(spot: Spot) -> str:
    """A workflow command; its message starts with where, since the log
    shows only the message for each past GitHub's first ten."""
    f, at = spot.finding, f"{spot.path}:{spot.line}"
    where = f"file={_escape(spot.path, True)},line={spot.line}"
    level = "error" if f.blocking else "warning"
    title = _escape(f"Illiana: {f.title}", True)
    return f"::{level} {where},title={title}::" + _escape(
        f"{at} {f.check}: {f.why} {f.action}"
    )


def _escape(value: str, prop: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value
