"""What a coding agent's hooks tell the app while a run is going.

Claude Code posts each step to the app as it takes it (``settings``, its
own settings shape, given to a session with ``--settings``): the event
names its session, which is how the app finds the run (``runs.note``), and
is read here for what the run is doing (``activity_of``). Another agent's
hooks need only post an event this module can read.
"""

from pathlib import PurePosixPath
from typing import Any

from .protocol import RUNS

# Where an agent's hooks post, under the app's address.
PATH = f"{RUNS}/activity"
# The variable an agent's hooks read the runner's token from: the runner
# gives it to every command, and a terminal session sets it itself.
TOKEN_ENV = "RUNNER_TOKEN"
# The events posted: a tool about to run, the agent waiting on someone, and
# the agent done with its turn.
TOOL, WAITING, ENDED = "PreToolUse", "Notification", "Stop"
EVENTS = (TOOL, WAITING, ENDED)
# What an agent that ended its turn is doing.
NOTHING = ""
# What a tool is on, in the order looked for: a file, the agent's own words
# for the step (before a command line, which may hold a secret), a
# command, a search, an address.
_ON = ("file_path", "description", "command", "pattern", "url")


def settings(url: str) -> dict[str, Any]:
    """Claude Code settings that post each step of a session to the app at
    ``url``, signed with the runner's token as its environment has it
    (``TOKEN_ENV``). A hook that cannot reach the app never fails the
    step, and gives up in seconds."""
    hook = {
        "type": "http",
        "url": url.rstrip("/") + PATH,
        "headers": {"Authorization": f"Bearer ${TOKEN_ENV}"},
        "allowedEnvVars": [TOKEN_ENV],
        "timeout": 2,
    }
    return {"hooks": {event: [{"hooks": [hook]}] for event in EVENTS}}


def activity_of(event: dict[str, Any]) -> str | None:
    """What an agent's event says its run is doing, in a few words: the
    tool about to run and what it is on (a file by its place in the
    worktree, an address without its query, anything else by its first
    line), that it waits on someone, or ``NOTHING`` once it ended its
    turn. None for an event that says none of these."""
    kind = event.get("hook_event_name")
    if kind == ENDED:
        return NOTHING
    if kind == WAITING and event.get("message"):
        return f"Waiting on you: {event['message']}"
    tool = event.get("tool_name")
    if kind != TOOL or not tool:
        return None
    given = event.get("tool_input")
    given = given if isinstance(given, dict) else {}
    key = next((key for key in _ON if given.get(key)), None)
    on = str(given[key]).strip().partition("\n")[0] if key else ""
    if key == "file_path":
        on = _within(on, str(event.get("cwd") or ""))
    elif key == "url":
        on = on.partition("?")[0]
    return f"{tool} {on}".strip()


def _within(path: str, cwd: str) -> str:
    """``path`` by its place under ``cwd``; in full where it is elsewhere."""
    if cwd and PurePosixPath(path).is_relative_to(cwd):
        return str(PurePosixPath(path).relative_to(cwd))
    return path
