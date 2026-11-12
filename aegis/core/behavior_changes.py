"""Operator-visible behavior changes, declared per template version.

``aegis update`` moves a project across template versions, and some of
those versions change what the running app *does* - not just its code.
The case that motivated this (#1029): 0.6.12 put the Flet dashboard behind
the auth service's login view whenever ``include_auth`` is on. A public
demo updated across that line came back as a gated app, and nothing in the
update output said so or named the flag that keeps the old behavior.

Nothing here is inferred. Deriving "this diff changes behavior" from a
template diff means a rule per release forever, and a model summarising
the changelog is out of scope for a CLI that must run offline. Instead
the author declares the change at the moment they know it, and the code
only decides whether to *show* it: does the update cross ``since``, and
does this stack have the component the change touches?

Adding an entry is the whole maintenance cost, and it happens once, in
the same PR that changes the behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from packaging.version import InvalidVersion, Version, parse

from ..constants import AnswerKeys
from .component_files import SCHEDULER_PERSISTENCE, group_on

Answers = dict[str, Any]


@dataclass(frozen=True)
class BehaviorChange:
    """One operator-visible change, introduced at ``since``."""

    since: str  # template version that introduced it, no leading "v"
    when: Callable[[Answers], bool]  # does it apply to this stack?
    message: str  # what changed, in one or two sentences
    restore: str | None = None  # the setting that keeps the OLD behavior


BEHAVIOR_CHANGES: tuple[BehaviorChange, ...] = (
    BehaviorChange(
        since="0.6.12",
        when=lambda a: group_on(AnswerKeys.AUTH, a),
        message=(
            "The Flet dashboard now sits behind the auth service's login view. "
            "A dashboard that was public before this version requires sign-in "
            "after it."
        ),
        restore="AUTH_ENABLED=false in .env keeps the dashboard open (synthetic dev user).",
    ),
    BehaviorChange(
        since="0.7.0",
        when=lambda a: group_on(AnswerKeys.SCHEDULER, a)
        and group_on(SCHEDULER_PERSISTENCE, a),
        message=(
            "The scheduler now treats code as the source of truth for jobs: "
            "on boot it deletes every persisted job whose id is not registered "
            "in create_scheduler. Schedules added at runtime (UI/CLI) count as "
            "orphans on the first boot after this update."
        ),
        restore=(
            "The deleted rows are exported to DATABASE_BACKUP_DIR/orphan_jobs_<ts>.json "
            "before removal; register the ones you want in create_scheduler."
        ),
    ),
)


def _parse(version: str) -> Version | None:
    try:
        return parse(version.removeprefix("v"))
    except InvalidVersion:
        return None


def behavior_changes_for(
    *, from_version: str, to_version: str, answers: Answers
) -> list[BehaviorChange]:
    """Changes this update crosses that apply to this stack.

    A change is crossed when ``from_version < since <= to_version``. A
    prerelease sorts before its release (``0.6.12-rc1 < 0.6.12``), so a
    project on the rc has not crossed the gate and is told.

    When ``from_version`` is not a version at all - a bare sha from a
    dev-mode init, or ``HEAD`` - the project cannot be placed on the line.
    Every applicable change up to ``to_version`` is reported: a notice the
    operator did not need is the safe failure, a silent behavior flip is
    not.
    """
    lo = _parse(from_version)
    hi = _parse(to_version)
    hits: list[BehaviorChange] = []
    for change in BEHAVIOR_CHANGES:
        since = _parse(change.since)
        if since is None or not change.when(answers):
            continue
        if hi is not None and since > hi:
            continue
        if lo is not None and since <= lo:
            continue
        hits.append(change)
    return hits
