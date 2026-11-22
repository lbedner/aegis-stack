"""What the runner and the app say to each other: what a runner sends to
claim a run, the run it is handed, and the answer it posts back.

Both sides read these, so neither spells the other's fields: the routes
take and return them (``backend/api/runner.py``) and the runner sends and
reads them (``client.py``). Nothing here touches the database, so the
runner imports it where there is none.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Where a runner, and its agent's hooks, reach the app's runs.
RUNS = "/api/v1/runner/runs"
# Where a runner claims a run, and posts what one came back with (the
# route's own template: ``FINISH.format(run_id=...)``).
CLAIM = f"{RUNS}/claim"
FINISH = f"{RUNS}/{{run_id}}/finish"
# Where a runner posts its agent's session as it goes (``Lines``).
LINES = f"{RUNS}/{{run_id}}/lines"
# What a runner gives a command where it is told nothing else, in seconds.
TIMEOUT_SECONDS = 900.0
# The most a run keeps of what came back.
KEEP = 20_000
# The most a run keeps of its agent's name.
MOST_AGENT = 64
# What an agent's session says, a line at a time: what it said, a tool it
# called with what it was given, what the tool gave back. Each is cut to
# ``MOST_LINE``, and a post carries at most ``MOST_LINES``.
SAID, CALLED, RETURNED = "said", "called", "returned"
MOST_LINE = 2_000
MOST_LINES = 200
# The run a runner answers itself, never its agent: push a run's branch
# and open its pull request, its prompt what the request's body ends
# with (``Closes acme/app#12``). Every runner takes it, with a GitHub
# token in its environment (``GITHUB_TOKEN_ENV``: one repository,
# Contents and Pull requests read and write), else says it has none.
PUSH = "push"
GITHUB_TOKEN_ENV = "RUNNER_GITHUB_TOKEN"
# How an agent says it has no answer: the last line of what it says, as
# every question it is asked tells it (work on a branch is not asked).
NO_ANSWER_MARK = "[no answer]"
NO_ANSWER_ASKED = (
    "If you find no answer, say why, then end with a line that says only "
    f"{NO_ANSWER_MARK}"
)
# A repository on GitHub, as its owner and name say it (``acme/app``).
GITHUB_REPO = r"[\w.-]+/[\w.-]+?"


def kept(result: str, ok: bool) -> str:
    """What a run keeps of ``result``: the start of an answer, the end of
    a failure, where the error is. The runner cuts it before it posts; the
    app cuts whatever is posted."""
    return result[:KEEP] if ok else result[-KEEP:]


class ClaimRequest(BaseModel):
    """What a runner asks for, and what the app needs to know of it to say
    where a run's work will be and when to stop waiting for it."""

    actions: list[str] = Field(description="The actions this runner runs")
    agent: str | None = Field(
        None,
        max_length=MOST_AGENT,
        description="The agent it runs them with: its command's program",
    )
    worktrees: str | None = Field(
        None, description="The folder it keeps a branch's worktree under"
    )
    timeout: float | None = Field(
        None,
        gt=0,
        lt=1e9,  # a span of time, so when to stop waiting is a date
        description="Seconds it gives a command before stopping it",
    )


class ClaimedRun(BaseModel):
    """A run handed to a runner."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    prompt: str
    branch: str | None = Field(None, description="Keep its worktree, on this branch")
    session_id: str | None = Field(None, description="The agent's session")
    resume: bool = Field(False, description="A runner took the session before")


class Answer(BaseModel):
    """What a run came back with: whether it succeeded, what it said, what
    the agent says its session has cost so far, and where its work is
    kept."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    result: str
    cost: float | None = Field(
        None,
        ge=0,
        allow_inf_nan=False,
        description="The agent's session, in dollars",
    )
    worktree: str | None = Field(None, description="Where its work is kept")
    unanswered: bool = Field(False, description="Its agent said it has no answer")
    unpushed: int | None = Field(
        None, ge=0, description="Its branch's commits the remote does not have"
    )


class Line(BaseModel):
    """One line of an agent's session, as its runner heard it."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["said", "called", "returned"]
    text: str


class Lines(BaseModel):
    """What a runner heard of its agent's session since it last posted."""

    lines: list[Line] = Field(max_length=MOST_LINES)
