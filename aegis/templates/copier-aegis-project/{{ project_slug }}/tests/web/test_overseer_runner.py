"""Overseer > Runner: the runs asked of a coding agent, newest first, each
by what was asked, with where it stands, how long it took and what it
cost; a row opens the run whole, with the worktree and session that pick
it up from a terminal."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import col, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import runs
from app.components.runner.health import RunnerFact
from app.components.runner.models import (
    CLAIMED,
    DONE,
    FAILED,
    RunnerRun,
    RunnerSpend,
    RunnerStep,
)
from app.components.runner.protocol import CALLED, PUSH, RETURNED, SAID
from app.components.web_frontend import overseer_runner
from app.components.web_frontend.assets import STATIC_DIR
from app.core.constants import ComponentName
from app.core.runtime import Instance
from app.core.time import utcnow
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus
from tests._fake_runtime import FakeRuntime, use_runtime
from tests._runner import WHERE, a_run, answered, asked, claimed, someone_else
from tests._session import opens
from tests.web.dom import (
    none,
    one,
    select,
    stat,
    table_rows,
    table_text,
    text,
    unfolded,
)
from tests.web.overseer import frame_html, page_html, sent_events, sign_in, status_with

PAGE = "/overseer/components/runner"
RUNNER = ComponentStatus(
    name=ComponentName.RUNNER, message="", metadata={RunnerFact.WAITING: 3}
)
BRANCH = WHERE.rsplit("/", 1)[1]
# The list's own table: a fold holds another.
RUNS = "#runner-runs > div > table"


@pytest.fixture
def overseer(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    sign_in(app, monkeypatch, status_with(RUNNER))
    return async_client_with_db


def test_a_stack_that_asked_nothing_says_so(overseer: TestClient) -> None:
    html = page_html(overseer, PAGE)

    assert text(one(html, "#runner-runs")) == overseer_runner.NO_RUNS
    assert stat(one(html, "#runner-figures"), "Cost") == "-"  # nothing spent


def test_its_dev_service_shows_on_its_page(overseer: TestClient) -> None:
    """The runner beside the app (``make serve``'s) is the component's
    agent: its container and its logs are sections of this page."""
    html = page_html(overseer, PAGE)

    links = [text(a) for a in select(html, "#overseer-subnav nav a")]
    assert links == ["Overview", "Container", "Logs"]


async def test_its_home_card_is_the_queues_figures_not_its_dev_services(
    overseer: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dev service acts for the component, it is not its process: the
    card on Overseer's home says how the queue is doing, never how much
    memory a developer's agent is using."""
    box = Instance(id="n1", name="app-runner-1", service="runner", state="running")
    use_runtime(monkeypatch, FakeRuntime(box))
    rows = (await ui_runtime.containers("runner"))["rows"]  # read, as its page does
    assert [row["name"] for row in rows] == [box.name]

    card = one(page_html(overseer, "/overseer"), '[data-card="runner"]')

    assert "Waiting" in text(card)
    assert box.name not in text(card)


async def _timed(db: AsyncSession, run_id: int) -> None:
    """The run claimed a minute and a half before it was back."""
    back = datetime(2026, 11, 18, 12, 0)
    await db.exec(
        update(RunnerRun)
        .where(col(RunnerRun.id) == run_id)
        .values(claimed_at=back - timedelta(seconds=90), finished_at=back)
    )


def _asked(html: str) -> list[tuple[str, str]]:
    """Each run listed: what was asked, and the line under it."""
    cells = select(html, f"{RUNS} tbody td:first-child")
    return [(text(one(cell, "a")), text(one(cell, "[data-sub]"))) for cell in cells]


async def test_a_run_reads_as_what_was_asked_and_where(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """Its asker's words for it, then its action and where it was asked;
    where its work is kept is the drawer's to say."""
    await asked(async_db_session, title="Fix the export", source="Tracker · acme/app")

    html = page_html(overseer, PAGE)

    assert _asked(html) == [("Fix the export", "agent · Tracker · acme/app")]
    [row] = table_text(html, RUNS)
    assert list(row) == ["What was asked", "Took", "Cost", "Result", "Asked"]
    assert (row["Result"], row["Took"], row["Cost"]) == ("Waiting", "-", "-")


async def test_a_run_its_asker_gave_no_words_for_reads_as_its_subject(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    await asked(async_db_session)

    assert _asked(page_html(overseer, PAGE)) == [("issue acme/app#12", "agent")]


async def test_a_run_going_says_what_its_agent_is_doing(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    await claimed(async_db_session, await asked(async_db_session, session_id="0f0f"))
    await runs.note(async_db_session, None, "0f0f", "Edit app/main.py")

    [row] = table_text(page_html(overseer, PAGE), RUNS)

    assert row["Result"] == "Running Edit app/main.py"


async def test_runs_are_newest_first_and_a_finished_one_says_what_it_took(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    done = await answered(async_db_session, await asked(async_db_session), cost=0.25)
    await _timed(async_db_session, done.id or 0)
    await asked(async_db_session, "acme/app#13")

    html = page_html(overseer, PAGE)

    assert [asked for asked, _ in _asked(html)] == [
        "issue acme/app#13",
        "issue acme/app#12",
    ]
    _, finished = table_text(html, RUNS)
    assert (finished["Took"], finished["Cost"]) == ("1m 30s", "$0.2500")


@pytest.mark.parametrize(
    ("back", "result", "tone"),
    [
        ({"result": "Yes."}, "Answered", "ok"),
        # Work on a branch is done, not an answer.
        ({"result": "Fixed.", "branch": "issue-12"}, "Done", "ok"),
        # Its command succeeded and said nothing.
        ({"result": ""}, "No answer", "warn"),
        # Its agent said it has none, and why.
        ({"result": "Nothing in the notes.", "unanswered": True}, "No answer", "warn"),
    ],
)
async def test_a_run_that_is_back_says_how_it_went(
    overseer: TestClient,
    async_db_session: AsyncSession,
    back: dict[str, Any],
    result: str,
    tone: str,
) -> None:
    async_db_session.add(a_run(status=DONE, **back))
    await async_db_session.flush()

    said = one(page_html(overseer, PAGE), f"{RUNS} tbody [data-tone]")

    assert (text(said), said.get("data-tone")) == (result, tone)


async def test_a_run_that_stopped_keeps_its_last_step_out_of_the_list(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """What it was doing when it stopped is the drawer's, as its last
    step: the list says only that it failed."""
    run = await asked(async_db_session, session_id="0f0f")
    await claimed(async_db_session, run)
    await runs.note(async_db_session, None, "0f0f", "Edit app/main.py")
    await runs.stop(async_db_session, run.subject_kind, [run.subject_id])

    [row] = table_text(page_html(overseer, PAGE), RUNS)
    drawer = page_html(overseer, overseer_runner.drawer_url(run.id or 0))

    assert row["Result"] == "Failed"
    assert stat(drawer, "Last step") == "Edit app/main.py"


async def test_a_status_the_page_does_not_know_still_lists(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """A status is any short word to the table: an app's own must not take
    the page down."""
    run = await asked(async_db_session)
    await async_db_session.exec(
        update(RunnerRun).where(col(RunnerRun.id) == run.id).values(status="parked")
    )

    [row] = table_text(page_html(overseer, PAGE), RUNS)

    assert row["Result"] == "parked"


async def test_the_figures_say_how_the_queue_stands_and_what_the_week_cost(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """What failed lately stands out, and both it and the cost say over
    how long."""
    now = utcnow()
    async_db_session.add_all(
        [
            a_run(),
            a_run(status=CLAIMED),
            a_run(status=CLAIMED),
            a_run(status=FAILED, finished_at=now),
            a_run(status=DONE, finished_at=now),
            RunnerSpend(action="agent", cost=0.25, at=now),
        ]
    )
    await async_db_session.flush()

    figures = one(page_html(overseer, PAGE), "#runner-figures")

    labels = ("Waiting", "Running", "Failed", "Cost")
    assert [stat(figures, label) for label in labels] == ["1", "2", "1", "$0.2500"]
    failed = one(figures, '[data-tone="error"]')
    assert (text(failed), text(failed.getnext())) == ("1", "Last 7 days")


async def _two_actions(db: AsyncSession) -> int:
    """An agent's run waiting and an ``ai`` run waiting: the latter's id."""
    await asked(db)
    return (await asked(db, "acme/app#13", action="ai")).id or 0


def _chips(html: str) -> list[tuple[str, str | None]]:
    """Each filter chip and its address, in order, the one chosen marked."""
    return [
        (text(a) + (" (on)" if a.get("aria-current") else ""), a.get("href"))
        for a in select(html, 'nav[aria-label="Action"] a')
    ]


async def test_runs_of_more_than_one_action_can_be_kept_to_one(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """The figures follow the list: both are the chosen action's."""
    await _two_actions(async_db_session)

    html = page_html(overseer, f"{PAGE}?action=ai")

    assert _chips(html) == [
        ("All", PAGE),
        ("agent", f"{PAGE}?action=agent"),
        ("ai (on)", f"{PAGE}?action=ai"),
    ]
    assert _asked(html) == [("issue acme/app#13", "ai")]
    assert stat(one(html, "#runner-figures"), "Waiting") == "1"


async def test_every_run_lists_until_an_action_it_has_is_chosen(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    await _two_actions(async_db_session)

    html = page_html(overseer, f"{PAGE}?action=nonesuch")

    assert _chips(html)[0] == ("All (on)", PAGE)
    assert len(_asked(html)) == 2


async def test_a_row_opens_its_run_over_the_list_as_it_was_kept(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    theirs = await _two_actions(async_db_session)

    link = one(page_html(overseer, f"{PAGE}?action=ai"), f"{RUNS} tbody a")

    assert link.get("href") == f"{PAGE}?action=ai&run={theirs}"


async def test_runs_of_one_action_offer_no_filter(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    await asked(async_db_session)

    assert _chips(page_html(overseer, PAGE)) == []


# Where a test's runs were asked together, the row that holds them, and
# the runs inside it.
PLACE = "Meeting · Weekly sync · 2026-11-16"
FOLD = f"{RUNS} > tbody"
INSIDE = "#runner-runs tr[data-detail] tbody tr"


async def test_runs_asked_in_one_place_of_one_action_fold_into_a_row(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """A meeting's questions read as one row: how many, how long and how
    much together, and how they went, the worst first to the eye. The
    questions are inside it, each still opening its run."""
    back = datetime(2026, 11, 18, 12, 0)
    took = {"claimed_at": back - timedelta(seconds=45), "finished_at": back}
    over = {"source": PLACE, "status": DONE, **took}
    async_db_session.add_all(
        [
            a_run(title="First?", result="Yes.", cost=0.25, **over),
            a_run(title="Second?", result="", cost=0.5, **over),
        ]
    )
    await async_db_session.flush()

    html = page_html(overseer, PAGE)

    [fold] = table_rows(html, RUNS)
    asked = fold["What was asked"]
    assert (
        text(asked).startswith(PLACE)
        and text(one(asked, "[data-sub]")) == "agent · 2 runs"
    )
    assert (text(fold["Took"]), text(fold["Cost"])) == ("1m 30s", "$0.7500")
    said = one(fold["Result"], "[data-tone]")
    assert (text(said), said.get("data-tone")) == ("1 No answer, 1 Answered", "warn")
    assert [text(a) for a in select(html, f"{INSIDE} a")] == ["Second?", "First?"]
    none(html, "[data-cut]")


@pytest.mark.parametrize(
    ("standing", "opened"),
    [
        ({"status": DONE, "result": "Yes."}, False),
        ({"status": CLAIMED}, True),
        ({"status": FAILED, "finished_at": utcnow()}, True),
        # What failed long ago no longer holds its fold open.
        ({"status": FAILED, "finished_at": datetime(2020, 1, 1)}, False),
    ],
)
async def test_a_fold_opens_by_itself_while_a_run_in_it_wants_a_look(
    overseer: TestClient,
    async_db_session: AsyncSession,
    standing: dict[str, Any],
    opened: bool,
) -> None:
    done = {"status": DONE, "result": "Yes."}
    async_db_session.add_all(
        [a_run(source=PLACE, **done), a_run(source=PLACE, **standing)]
    )
    await async_db_session.flush()

    assert unfolded(page_html(overseer, PAGE), FOLD) is opened


async def test_the_fold_a_run_was_opened_from_stays_open(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    held = [a_run(source=PLACE, status=DONE, result="Yes.") for _ in range(2)]
    async_db_session.add_all(held)
    await async_db_session.flush()

    assert unfolded(page_html(overseer, f"{PAGE}?run={held[0].id}"), FOLD)


async def test_runs_fold_only_with_their_own_action_in_their_own_place(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """Another action's are another row, a lone run stays a row of its
    own with nothing to unfold, and runs that say no place never fold."""
    async_db_session.add_all(
        [
            a_run(source=PLACE, action="ai"),
            a_run(source=PLACE, action="ai"),
            a_run(source=PLACE, title="Alone?"),
            a_run(),
            a_run(),
        ]
    )
    await async_db_session.flush()

    rows = table_rows(page_html(overseer, PAGE), RUNS)

    unfold = [bool(select(row["Details"], "button")) for row in rows]
    assert unfold == [False, False, False, True]
    assert text(one(rows[2]["What was asked"], "a")) == "Alone?"


@pytest.mark.parametrize(
    ("agent", "icon"),
    [
        # The agent's own mark, where the icons draw its maker's.
        ("claude", "claude-code"),
        # However its program is spelled, and by the icon that is its own.
        ("Gemini", "gemini-ai"),
        # What starts an agent is not one, though the icons draw it too.
        ("python", "robot"),
        ("nonesuch", "robot"),
        (None, "robot"),
    ],
)
async def test_a_run_is_marked_with_its_agents_icon(
    overseer: TestClient,
    async_db_session: AsyncSession,
    agent: str | None,
    icon: str,
) -> None:
    async_db_session.add(a_run(agent=agent))
    await async_db_session.flush()

    mark = one(page_html(overseer, PAGE), f"{RUNS} tbody img")

    assert f"/{icon}.svg" in mark.get("src")


def test_every_agent_the_page_marks_has_its_icon() -> None:
    """Most of the icons are another project's: one it drops must not
    leave a broken image."""
    drawn = {*overseer_runner.AGENT_ICONS.values(), overseer_runner.PLAIN_AGENT}

    assert [icon for icon in drawn if not (STATIC_DIR / icon).is_file()] == []


@pytest.mark.parametrize(
    ("agents", "icon"),
    [
        (("claude", "claude"), "claude-code"),
        # One still waiting has no agent yet: the rest say whose they are.
        (("claude", None), "claude-code"),
        (("claude", "gemini"), "robot"),
    ],
)
async def test_a_fold_is_marked_with_the_agent_its_runs_share(
    overseer: TestClient,
    async_db_session: AsyncSession,
    agents: tuple[str | None, str | None],
    icon: str,
) -> None:
    async_db_session.add_all([a_run(source=PLACE, agent=agent) for agent in agents])
    await async_db_session.flush()

    [fold] = table_rows(page_html(overseer, PAGE), RUNS)

    assert f"/{icon}.svg" in one(fold["What was asked"], "img").get("src")


async def test_the_drawer_names_the_agent_with_its_runner(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    run = a_run(runner="laptop", agent="claude", status=DONE, result="Yes.")
    async_db_session.add(run)
    await async_db_session.flush()

    html = page_html(overseer, overseer_runner.drawer_url(run.id or 0))

    assert stat(html, "Runner") == "laptop · claude"


async def test_the_drawer_says_what_the_agent_did_under_what_came_back(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """Each step its agent took, in order and when, so a reader can see
    what an answer rests on."""
    db = async_db_session
    run_id = await _finished(db, "Yes.")
    at = datetime(2026, 11, 18, 12, 0, 5)
    db.add_all(
        RunnerStep(run_id=run_id, at=at + timedelta(seconds=n), step=step)
        for n, step in enumerate(("Read app/main.py", "Bash Run the tests"))
    )
    await db.commit()

    html = page_html(overseer, overseer_runner.drawer_url(run_id))

    sections = [section.get("id") for section in select(html, "section")]
    assert sections[:2] == ["run-result", "run-steps"]
    assert [text(li) for li in select(html, "#run-steps li")] == [
        "12:00:05 Read app/main.py",
        "12:00:06 Bash Run the tests",
    ]


async def test_two_owners_runs_in_a_place_of_one_name_stay_apart(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """The page lists every owner's runs, and a place is its owner's."""
    owners = [await someone_else(async_db_session) for _ in range(2)]
    async_db_session.add_all(
        [a_run(source=PLACE, owner_user_id=owner) for owner in owners]
    )
    await async_db_session.flush()

    assert len(table_rows(page_html(overseer, PAGE), RUNS)) == 2


async def test_a_list_cut_short_says_so_and_its_last_fold_counts_what_is_listed(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(overseer_runner, "SHOWN", 2)
    async_db_session.add_all([a_run(source=PLACE) for _ in range(3)])
    await async_db_session.flush()

    html = page_html(overseer, PAGE)

    [fold] = table_rows(html, RUNS)
    assert text(one(fold["What was asked"], "[data-sub]")) == "agent · 2 runs"
    assert text(one(html, "[data-cut]")) == (
        "The newest 2 runs. Older ones are not listed."
    )


async def _finished(db: AsyncSession, result: str, *, ok: bool = True) -> int:
    """A run on a branch a runner took and brought back as ``result``."""
    run = await asked(
        db,
        branch=BRANCH,
        session_id="0f0f",
        prompt="Fix the export.",
        title="Can the export ship?",
        source="Meeting · Weekly sync",
    )
    await answered(db, run, result, ok=ok, cost=0.25, worktree=WHERE)
    return run.id or 0


async def test_a_row_links_to_its_run_and_no_drawer_is_open_until_then(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    run_id = await _finished(async_db_session, "Fixed.")

    listed = page_html(overseer, PAGE)

    link = one(listed, f"{RUNS} tbody a")
    assert text(link) == "Can the export ship?"
    assert link.get("href") == f"{PAGE}?run={run_id}"
    assert one(listed, "[data-drawer-sync]").get("data-drawer-url") == ""


async def test_a_row_opens_its_run_in_the_drawer(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    run_id = await _finished(async_db_session, "Fixed.")

    opened = one(page_html(overseer, f"{PAGE}?run={run_id}"), "[data-drawer-sync]")

    assert opened.get("data-drawer-url") == overseer_runner.drawer_url(run_id)
    assert opened.get("data-drawer-param") == overseer_runner.DRAWER_PARAM


async def test_the_drawer_leads_with_what_was_asked_and_what_came_back(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """The question in its asker's words, then the answer as a chat reply
    reads (markdown), then the facts; what the agent was sent (a meeting's
    transcript and all) stays folded, and the run's own id is small."""
    answer = "**Fixed.**\n\n- `export.py` ships it.\n- Tests pass."
    run_id = await _finished(async_db_session, answer)
    await _timed(async_db_session, run_id)

    html = page_html(overseer, overseer_runner.drawer_url(run_id))

    assert text(select(html, "h2")[0]) == "Can the export ship?"
    assert text(one(html, "h2 + p")) == f"Run {run_id} · issue acme/app#12"
    assert [section.get("id") for section in select(html, "section")] == [
        "run-result",
        "run-facts",
        "run-prompt",
    ]
    assert len(select(html, "#run-result [data-answer] ul > li")) == 2
    folded = one(html, "#run-prompt details")
    assert folded.get("open") is None and "Fix the export." in text(folded)
    assert stat(html, "From") == "Meeting · Weekly sync"
    assert stat(html, "Action") == "agent"
    assert stat(html, "Runner") == "laptop"
    assert stat(html, "Took") == "1m 30s"
    assert stat(html, "Cost") == "$0.2500"
    assert stat(html, "Worktree") == WHERE
    assert stat(html, "Session") == "0f0f"


async def test_a_run_still_waiting_opens_with_only_what_is_known(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    """Nothing took it yet: no runner, no time taken, nothing back; and
    one its asker gave no words for is titled by its subject, said once."""
    run = await asked(async_db_session, prompt="Fix the export.")

    html = page_html(overseer, overseer_runner.drawer_url(run.id or 0))

    assert text(select(html, "h2")[0]) == "issue acme/app#12"
    assert text(one(html, "h2 + p")) == f"Run {run.id}"
    assert "Fix the export." in text(one(html, "#run-prompt"))
    none(html, "#run-result")
    labels = [text(dt) for dt in select(html, "#run-facts dt")]
    assert "Action" in labels and not {"Runner", "Took", "Cost"} & set(labels)


async def test_a_failed_run_says_why_as_it_was_said(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    run_id = await _finished(async_db_session, "error: **not** a repo", ok=False)

    html = page_html(overseer, overseer_runner.drawer_url(run_id))

    assert text(one(html, "#run-result [data-answer]")) == "error: **not** a repo"


def test_a_run_that_is_gone_is_not_found(overseer: TestClient) -> None:
    response = overseer.get(overseer_runner.drawer_url(999))

    assert response.status_code == 404
    assert overseer_runner.NO_RUN in response.text


async def _back_with(db: AsyncSession, unpushed: int) -> int:
    """A run on a branch back with ``unpushed`` commits not on the remote."""
    run = await asked(db, branch=BRANCH, prompt="Fix the export.")
    await answered(db, run, "Fixed.", unpushed=unpushed, worktree=WHERE)
    return run.id or 0


@pytest.mark.parametrize(
    ("unpushed", "said"), [(1, "1 commit not on GitHub"), (0, None)]
)
async def test_the_drawer_says_what_is_not_pushed_and_offers_to_push_it(
    overseer: TestClient,
    async_db_session: AsyncSession,
    unpushed: int,
    said: str | None,
) -> None:
    run_id = await _back_with(async_db_session, unpushed)

    html = page_html(overseer, overseer_runner.drawer_url(run_id))

    if said is None:
        none(html, "[data-push]")
        return
    assert text(one(html, "[data-push] p")) == said
    button = one(html, "[data-push] button")
    assert button.get("hx-post") == overseer_runner.push_url(run_id)


async def test_pressing_push_asks_it_and_the_drawer_says_it_is_pushing(
    overseer: TestClient, async_db_session: AsyncSession
) -> None:
    run_id = await _back_with(async_db_session, 1)

    pressed = overseer.post(
        overseer_runner.push_url(run_id), headers={"HX-Request": "true"}
    )

    assert pressed.status_code == 200
    assert "Pushing" in text(one(pressed.text, "[data-push]"))
    none(pressed.text, "[data-push] button")
    (push,) = [
        r
        for r in await runs.about(async_db_session, "issue", ["acme/app#12"])
        if r.action == PUSH
    ]
    assert push.branch == BRANCH


@pytest.mark.parametrize(
    ("status", "result", "button"),
    [
        (DONE, "https://github.com/acme/app/pull/5", False),
        (FAILED, "No RUNNER_GITHUB_TOKEN where this runner runs", True),
    ],
)
async def test_a_push_back_shows_its_pull_request_or_why_not(
    overseer: TestClient,
    async_db_session: AsyncSession,
    status: str,
    result: str,
    button: bool,
) -> None:
    """Its link once done; why it did not push, with the button again."""
    db = async_db_session
    run_id = await _back_with(db, 1)
    db.add(a_run(action=PUSH, branch=BRANCH, status=status, result=result))
    await db.commit()

    html = page_html(overseer, overseer_runner.drawer_url(run_id))

    assert result in text(one(html, "[data-push]"))
    assert bool(select(html, "[data-push] button")) is button


@pytest.mark.parametrize("going", [True, False])
async def test_a_going_runs_drawer_follows_it_and_one_back_does_not(
    overseer: TestClient, async_db_session: AsyncSession, going: bool
) -> None:
    db = async_db_session
    run = await claimed(db, await asked(db))
    if not going:
        run.status, run.result = DONE, "Yes."
        await db.commit()

    html = page_html(overseer, overseer_runner.drawer_url(run.id or 0))

    if not going:
        none(html, "[sse-connect]")
        return
    live = one(html, "[sse-connect]")
    assert live.get("sse-connect") == overseer_runner.events_url(run.id or 0)
    assert live.get("sse-close") == overseer_runner.RUN_DONE
    assert one(live, "[sse-swap]").get("hx-swap") == "innerHTML"


async def test_a_going_runs_drawer_is_sent_as_it_goes(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = async_db_session
    monkeypatch.setattr(overseer_runner, "get_async_session", opens(db))
    run = await claimed(db, await asked(db))

    (going,) = await sent_events(
        overseer_runner.drawer_events(run.id or 0, max_frames=1)
    )

    assert going.startswith(f"event: {overseer_runner.RUN_EVENT}\n")
    assert "Running" in frame_html(going)


async def test_a_runs_stream_closes_once_it_is_back(
    overseer: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its last frame is what it came back with, then the event the page
    closes the stream on."""
    monkeypatch.setattr(overseer_runner, "get_async_session", opens(async_db_session))
    run = await answered(async_db_session, await asked(async_db_session), "Yes.")

    streamed = overseer.get(overseer_runner.events_url(run.id or 0))

    frames = [f for f in streamed.text.split("\n\n") if f.startswith("event:")]
    assert [f.split("\n")[0] for f in frames] == [
        f"event: {overseer_runner.RUN_EVENT}",
        f"event: {overseer_runner.RUN_DONE}",
    ]
    assert "Yes." in frame_html(frames[0])


@pytest.mark.parametrize("heard", [True, False])
async def test_the_drawer_shows_the_agents_session_like_a_terminal(
    overseer: TestClient, async_db_session: AsyncSession, heard: bool
) -> None:
    """Its lines in order, each marked by what it is; a runner that sent
    none leaves the steps its hooks posted."""
    db = async_db_session
    run = await claimed(db, await asked(db))
    db.add(RunnerStep(run_id=run.id or 0, step="Bash ls"))
    if heard:
        db.add_all(
            [
                RunnerStep(
                    run_id=run.id or 0, kind=CALLED, step='Bash {"command": "ls"}'
                ),
                RunnerStep(run_id=run.id or 0, kind=RETURNED, step="README.md"),
                RunnerStep(run_id=run.id or 0, kind=SAID, step="One file."),
            ]
        )
    await db.commit()

    html = page_html(overseer, overseer_runner.drawer_url(run.id or 0))

    if not heard:
        none(html, "[data-session]")
        assert text(one(html, "#run-steps")).endswith("Bash ls")
        return
    session = one(html, "[data-session]")
    assert session.get("data-follow") is not None
    assert [
        (line.get("data-kind"), text(line)) for line in select(session, "[data-kind]")
    ] == [
        (CALLED, 'Bash {"command": "ls"}'),
        (RETURNED, "README.md"),
        (SAID, "One file."),
    ]
    none(html, "#run-steps")
