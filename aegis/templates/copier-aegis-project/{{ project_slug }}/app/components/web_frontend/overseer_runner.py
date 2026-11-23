"""Overseer > Runner: the runs asked of a coding agent, every owner's,
newest first, each by what was asked (its asker's words, else its
subject): how long it took, what it cost and how it went (where it stands,
with what its agent is doing while it runs, ``hooks``; whether it answered,
once it is back). Over them, how the queue stands and what the last days
cost; runs of more than one action can be kept to one. Runs asked in one
place of one action fold into a row that holds them (a meeting's
questions). A run's row opens it in the drawer: what came back, where its
work is kept, and what was sent.

ponytail: read when the page is, so a reload shows the next step; over SSE
(``overseer_live``) when a run is watched here rather than where it was
asked. Opening a run reads the list again, so a fold opened by hand closes
unless it holds that run: load the drawer alone when that grates.
"""

from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from app.components.runner import runs
from app.components.runner.models import (
    ASKED,
    CLAIMED,
    FAILED,
    GOING,
    LABELS,
    RunnerRun,
    RunnerStep,
    outcome,
)
from app.core.constants import ComponentName
from app.core.db import get_async_session
from app.core.formatting import (
    counted,
    format_cost,
    format_relative_time,
    format_span,
    format_timestamp,
)
from app.core.time import utcnow
from app.services.system.models import ComponentStatus

from .assets import static_url
from .file_icons import FOLDER as ICONS
from .filters import loudness
from .overseer_live import until_done
from .overseer_nav import SectionRequest, page_url
from .rendering import (
    chips,
    drawer_state,
    fragment,
    hx_drawer_post,
    status_cell,
    with_query,
)

SECTIONS = ((None, {"overview": "Overview"}),)
PAGE = page_url("components", ComponentName.RUNNER)
# Where this page's drawer lives (``routes/partials/overseer_runner``).
PARTIALS = "/partials/overseer/runner"
DRAWER = "pages/overseer/runner/_drawer.html"
# What of it changes while a run goes, sent again as it does
# (``drawer_events``): as ``RUN_EVENT``, then ``RUN_DONE`` once it is back,
# which closes the stream; read again every ``LIVE_SECONDS``.
DRAWER_LIVE = "pages/overseer/runner/_drawer_live.html"
RUN_EVENT, RUN_DONE = "run", "run-done"
LIVE_SECONDS = 2.0
DRAWER_PARAM = "run"
# The query parameter keeping the list to one action's runs.
ACTION_PARAM = "action"
COLUMNS = [
    {
        "key": "asked",
        "label": "What was asked",
        "kind": "link",
        "target": "#overseer-main",
        "wrap": True,
        # The agent that ran it (``_mark``), before what was asked.
        "mark": True,
    },
    {"key": "took", "label": "Took", "align": "right"},
    {"key": "cost", "label": "Cost", "align": "right"},
    {"key": "status", "label": "Result", "kind": "status", "wrap": True},
    {"key": "when", "label": "Asked"},
]
# How far back the figures count what failed and what was spent.
LATELY = timedelta(days=7)
NO_RUNS = "No runs yet. A run shows here once something asks one."
NO_RUN = "There is no run by that id."
# The icon of each agent the page knows, by the program a runner starts
# (lowercased), as a static file: one of the icons the web frontend ships
# for files, or a mark of the page's own where those draw the agent's maker
# and not the agent. What starts an agent (``python``, ``npx``) is not one,
# though those icons draw it.
AGENT_ICONS = {
    "claude": "marks/claude-code.svg",
    "gemini": f"{ICONS}/gemini-ai.svg",
    "opencode": f"{ICONS}/opencode.svg",
    "cline": f"{ICONS}/cline.svg",
}
# The mark of a run whose agent is none of those, or that says none.
PLAIN_AGENT = f"{ICONS}/robot.svg"
CUT = "The newest {runs}. Older ones are not listed."
# The newest runs the page lists (folded, fewer rows than that).
SHOWN = 200


def drawer_url(run_id: int | str) -> str:
    """Where a run's drawer is read from."""
    return f"{PARTIALS}/{run_id}/drawer"


def events_url(run_id: int | str) -> str:
    """Where a run's drawer is followed while it goes."""
    return f"{PARTIALS}/{run_id}/events"


def _did(taken: list[RunnerStep]) -> dict[str, list[dict[str, str]]]:
    """What a run's agent did: its session as its runner heard it, a line
    each (``session``), and the steps its hooks posted (``steps``), which
    the drawer shows where its runner sent no session."""
    return {
        "session": [{"kind": s.kind, "text": s.step} for s in taken if s.kind],
        "steps": [
            {"when": format_timestamp(s.at.isoformat()), "what": s.step}
            for s in taken
            if not s.kind
        ],
    }


def push_url(run_id: int | str) -> str:
    """Where a run's branch is asked to be pushed."""
    return f"{PARTIALS}/{run_id}/push"


async def _push(
    db: Any, run: RunnerRun, pushed: RunnerRun | None
) -> dict[str, Any] | None:
    """What the drawer says of a run's branch on GitHub: its commits not
    there, how the push asked since went (``pushed``, else read) and what
    it said (its pull request's link, once done), and the button while no
    push is going or done; None when its runner counted nothing to push.
    The drawer follows a push that goes, as it does a run (``drawer``'s
    ``follow``)."""
    if not run.unpushed:
        return None
    pushed = pushed or await runs.pushed(db, run)
    status = pushed.status if pushed else None
    return {
        "unpushed": run.unpushed,
        "status": "going" if status in GOING else status,
        "result": pushed.result if pushed else None,
        "post": hx_drawer_post(push_url(run.id)) if status in (None, FAILED) else None,  # type: ignore[arg-type]
    }


def _about(run: RunnerRun) -> str:
    return f"{run.subject_kind} {run.subject_id}"


def _mark(agent: str | None) -> str:
    """Where the agent's icon is, by its program's name (``claude``)."""
    return static_url(AGENT_ICONS.get((agent or "").lower(), PLAIN_AGENT))


def _called(run: RunnerRun) -> str:
    """Its asker's words for it, else its subject."""
    return run.title or _about(run)


def _status(run: RunnerRun, back: bool, sub: str | None = None) -> dict[str, str]:
    """How the run went (``outcome``; ``back``: whether anything came
    back), with a line under it."""
    return status_cell(*outcome(run, back), sub)


def _cost(run: RunnerRun) -> str | None:
    return None if run.cost is None else format_cost(run.cost)


def _seconds(run: RunnerRun) -> float | None:
    """From claimed to back; nothing for a run not back yet."""
    if not (run.finished_at and run.claimed_at):
        return None
    return (run.finished_at - run.claimed_at).total_seconds()


def _row(
    run: RunnerRun, back: bool, action: str | None, folded: bool = False
) -> dict[str, Any]:
    """A run's row: one of its own (``flat``, among rows that unfold), or
    ``folded`` into one that already says its action and where it was
    asked."""
    opened = {ACTION_PARAM: action, DRAWER_PARAM: str(run.id)}
    return {
        "asked": {
            "label": _called(run),
            "url": with_query(PAGE, **opened),
            "sub": None
            if folded
            else " · ".join(filter(None, (run.action, run.source))),
        },
        "took": format_span(_seconds(run)),
        "cost": _cost(run),
        # What it is doing is said while it runs; a stopped run's last step
        # is the drawer's.
        "status": _status(run, back, run.activity if run.status == CLAIMED else None),
        "when": format_relative_time(run.asked_at),
        "icon_url": _mark(run.agent),
        "flat": not folded,
    }


def _fold(
    members: list[tuple[RunnerRun, bool]],
    action: str | None,
    wanted: str,
    lately: datetime,
) -> dict[str, Any]:
    """Runs asked in one place of one action (newest first) as one row: how
    many, how long and how much together, and how they went, what wants a
    look first. It opens by itself while one of them does: still going,
    failed since ``lately``, or the run the drawer shows (``wanted``)."""
    newest = members[0][0]
    # One still waiting has no agent yet: the rest say whose the fold is.
    agents = {run.agent for run, _ in members} - {None}
    went = Counter(outcome(run, back) for run, back in members)
    loud = sorted(went, key=lambda said: loudness(said[1]))
    took = [seconds for run, _ in members if (seconds := _seconds(run)) is not None]
    spent = [run.cost for run, _ in members if run.cost is not None]
    return {
        "asked": {
            "label": newest.source,
            "sub": f"{newest.action} · {counted(len(members), 'run')}",
        },
        "took": format_span(sum(took)) if took else None,
        "cost": format_cost(sum(spent)) if spent else None,
        "status": status_cell(
            ", ".join(f"{went[said]} {said[0]}" for said in loud), loud[0][1]
        ),
        "when": format_relative_time(newest.asked_at),
        # Its runs' agent, where they share one.
        "icon_url": _mark(next(iter(agents)) if len(agents) == 1 else None),
        "runs": [_row(run, back, action, folded=True) for run, back in members],
        "open": any(
            str(run.id) == wanted
            or run.status in GOING
            or (
                run.status == FAILED
                and bool(run.finished_at)
                and run.finished_at >= lately
            )
            for run, _ in members
        ),
    }


def _rows(
    listed: list[tuple[RunnerRun, bool]],
    action: str | None,
    wanted: str,
    lately: datetime,
) -> list[dict[str, Any]]:
    """The runs listed, newest first, those asked in one place of one
    action folded together (``_fold``) where its newest is. A place is its
    owner's: the list is every owner's. A run alone in its place, or that
    says no place, is a row of its own.

    ponytail: a place is its name, so two of one owner's that say the same
    one fold together (meetings adds the day to a meeting's); and the fold
    at the cut counts only the runs listed. A place's id on the run, and folding
    in the database, when either misleads.
    """
    folds: dict[Any, list[tuple[RunnerRun, bool]]] = {}
    for run, back in listed:
        its = (run.source, run.action, run.owner_user_id)
        place = its if run.source else run.id
        folds.setdefault(place, []).append((run, back))
    return [
        _fold(members, action, wanted, lately)
        if len(members) > 1
        else _row(*members[0], action)
        for members in folds.values()
    ]


def _figures(tally: list[runs.Tally]) -> list[dict[str, Any]]:
    """How these actions' runs stand, and what failed and was spent
    lately (what was written down as spent: ``queries.spend``)."""
    failed, spent = sum(t.failed for t in tally), sum(t.cost for t in tally)
    lately = f"Last {LATELY.days} days"
    return [
        {"label": LABELS[ASKED], "value": sum(t.waiting for t in tally)},
        {"label": LABELS[CLAIMED], "value": sum(t.running for t in tally)},
        {
            "label": LABELS[FAILED],
            "value": failed,
            "caption": lately,
            "tone": "error" if failed else None,
        },
        {
            "label": "Cost",
            "value": format_cost(spent) if spent else "-",
            "caption": lately,
        },
    ]


def _chips(actions: list[str], chosen: str | None) -> list[dict[str, Any]]:
    """All, then each action; none where there is one action to choose."""
    if len(actions) < 2:
        return []
    choices = [(None, "All"), *zip(actions, actions, strict=True)]
    return chips(PAGE, ACTION_PARAM, choices, chosen)


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    wanted = req.query.get(DRAWER_PARAM) or ""
    drawer = drawer_url(wanted) if wanted.isdigit() else None
    lately = utcnow() - LATELY
    tally = await runs.tally(req.db, lately)
    actions = [t.action for t in tally]
    chosen = req.query.get(ACTION_PARAM)
    chosen = chosen if chosen in actions else None
    # One more than is shown says whether older ones were left out.
    listed = await runs.latest(req.db, SHOWN + 1, chosen)
    rows = _rows(listed[:SHOWN], chosen, wanted, lately)
    return drawer_state(DRAWER_PARAM, drawer) | {
        "figures": _figures([t for t in tally if chosen in (None, t.action)]),
        "chips": _chips(actions, chosen),
        "runs": rows,
        "folds": any("runs" in row for row in rows),
        "cut": CUT.format(runs=counted(SHOWN, "run")) if len(listed) > SHOWN else None,
        "run_columns": COLUMNS,
        "no_runs": NO_RUNS,
    }


async def drawer_context(db: Any, run_id: int) -> dict[str, Any] | None:
    """One run whole, or None when there is none by that id."""
    run = await runs.one(db, run_id)
    return None if run is None else await drawer(db, run)


async def drawer(
    db: Any, run: RunnerRun, pushed: RunnerRun | None = None
) -> dict[str, Any]:
    """``run`` whole, with the push of its branch just asked, if one was;
    followed (``events``) while it goes, or while that push does."""
    going, push = run.status in GOING, await _push(db, run, pushed)
    return {
        "going": going,
        "follow": going or bool(push and push["status"] == "going"),
        "events": events_url(run.id or 0),
        "event": RUN_EVENT,
        "done": RUN_DONE,
        "title": _called(run),
        # Its own id, and its subject where the title is not already it.
        "ids": " · ".join(filter(None, (f"Run {run.id}", run.title and _about(run)))),
        "status": _status(run, bool(run.result)),
        "facts": [
            ("Asked", format_relative_time(run.asked_at)),
            ("From", run.source),
            ("Action", run.action),
            # Its runner, and the agent that runner runs.
            ("Runner", " · ".join(filter(None, (run.runner, run.agent)))),
            ("Took", format_span(_seconds(run))),
            ("Cost", _cost(run)),
            # What a run that is over was doing is where it stopped.
            ("Doing" if run.status == CLAIMED else "Last step", run.activity),
            ("Branch", run.branch),
            ("Worktree", run.worktree),
            ("Session", run.session_id),
        ],
        **_did(await runs.steps(db, run.id or 0)),
        "push": push,
        "prompt": run.prompt,
        "result": run.result,
    }


def drawer_events(run_id: int, max_frames: int | None = None) -> AsyncIterator[str]:
    """A run's drawer over SSE: what changes while it, or a push of its
    branch, goes, sent again only when it does, until both are back
    (``until_done``). Its runner posts by
    HTTP and nothing announces a change, so the run is read each round.

    ponytail: each round reads and renders its whole session (up to
    ``MOST_STEPS`` lines) to find what changed; send only the lines past the
    last one sent (a ``beforeend`` swap) when sessions grow that long."""

    async def live() -> tuple[dict[str, str], bool]:
        async with get_async_session() as db:
            run = await runs.one(db, run_id)
            context = None if run is None else await drawer(db, run)
        if context is None:
            return {}, False
        return {RUN_EVENT: fragment(DRAWER_LIVE, **context)}, context["follow"]

    return until_done(live, RUN_DONE, LIVE_SECONDS, max_frames)
