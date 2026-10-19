"""``patterns check``: the findings a change brings, against the known debt
in ``.patterns-baseline.json`` (``check``).

Each place a finding shows (one ``path:line`` of its evidence) is known by
its rule, its part, its file and the text on that line, not the line's
number: code added above known debt does not make it new. Advisory: the
exit code is 0 unless ``strict`` and a new place breaks an enforced rule.
Under GitHub Actions each new place is a workflow command, which GitHub
shows on the pull request's diff; with ``GITHUB_STEP_SUMMARY`` set, what
the change touches and its new findings are written there too."""

from collections import Counter
from collections.abc import Iterable, Mapping
import json
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
    lines = [
        _annotation(s) if env.get("GITHUB_ACTIONS") else f"{s.at}: {_line(s)}"
        for s in fresh
    ]
    lines.append(f"{len(fresh)} new; {before.total()} known in {BASELINE}")
    if summary := env.get("GITHUB_STEP_SUMMARY"):
        rows = [f"- `{s.at}` {_line(s)}" for s in fresh]
        with open(summary, "a") as out:
            head = [touched] if touched else []
            out.write("\n".join([*head, "### New findings", "", *rows, ""]))
    failed = strict and any(s.finding.severity == "error" for s in fresh)
    return "\n".join(lines), int(failed)


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
    return f"::warning {where},title={_escape(f.check, True)}::" + _escape(
        f"{at} {f.check}: {f.why} {f.action}"
    )


def _escape(value: str, prop: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value
