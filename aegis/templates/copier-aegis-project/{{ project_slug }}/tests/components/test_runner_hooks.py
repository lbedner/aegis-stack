"""What a coding agent's hooks tell the app while a run is going: the
settings that make Claude Code post each step to the app, and what an
event says the run is doing."""

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from app.components.runner import hooks, protocol
from tests._cli import invoke
from tests._runner import WHERE, step


@pytest.mark.parametrize(
    ("event", "doing"),
    [
        pytest.param(
            step("Edit", file_path=f"{WHERE}/app/core/tokens.py"),
            "Edit app/core/tokens.py",
            id="a-file-by-its-place-in-the-worktree",
        ),
        pytest.param(
            step("Read", file_path="/etc/hosts"),
            "Read /etc/hosts",
            id="a-file-elsewhere-in-full",
        ),
        pytest.param(
            step(
                "Bash",
                command="curl -H 'Authorization: Bearer sk-live-1' https://x",
                description="Fetch the release notes",
            ),
            "Bash Fetch the release notes",
            id="a-command-in-the-agents-words-not-its-own",
        ),
        pytest.param(
            step("Bash", command="make test\necho done"),
            "Bash make test",
            id="a-commands-first-line-where-that-is-all-there-is",
        ),
        pytest.param(
            step("Grep", pattern="RunnerRun"),
            "Grep RunnerRun",
            id="what-it-searches-for",
        ),
        pytest.param(
            step("WebFetch", url="https://example.com/notes?token=abc"),
            "WebFetch https://example.com/notes",
            id="an-address-without-its-query",
        ),
        pytest.param(step("TodoWrite"), "TodoWrite", id="a-tool-alone"),
        pytest.param(
            {**step("Edit"), "tool_input": "app/main.py"},
            "Edit",
            id="a-tool-whose-input-is-no-object",
        ),
    ],
)
def test_a_tool_about_to_run_says_the_tool_and_what_it_is_on(
    event: dict[str, Any], doing: str
) -> None:
    assert hooks.activity_of(event) == doing


def test_an_agent_that_stopped_for_an_answer_is_waiting_on_you() -> None:
    event = {
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
        "message": "Claude needs your permission to use Bash",
    }

    assert hooks.activity_of(event) == (
        "Waiting on you: Claude needs your permission to use Bash"
    )


def test_an_agent_that_ended_its_turn_is_doing_nothing() -> None:
    """Told apart from an event that says nothing: this one clears what
    the run said it was doing."""
    assert hooks.activity_of({"hook_event_name": "Stop"}) == hooks.NOTHING


@pytest.mark.parametrize(
    "event",
    [
        {"hook_event_name": "SessionStart"},
        {"hook_event_name": "PreToolUse"},
        {"hook_event_name": "Notification"},
        {},
        {"tool_name": "Edit"},
    ],
)
def test_an_event_that_says_nothing_of_what_it_is_doing_is_no_activity(
    event: dict[str, Any],
) -> None:
    assert hooks.activity_of(event) is None


def test_the_settings_post_each_step_to_the_app_with_the_runners_token() -> None:
    """Claude Code's own settings shape and event names: an HTTP hook per
    event, signed with the token it reads from its environment, and quick
    to give up so an app out of reach never holds a tool call for long."""
    settings = hooks.settings("https://my-app.example.com/")

    assert set(settings["hooks"]) == {"PreToolUse", "Notification", "Stop"}
    for groups in settings["hooks"].values():
        ((hook,),) = (group["hooks"] for group in groups)
        assert hook["type"] == "http"
        assert hook["url"] == "https://my-app.example.com" + hooks.PATH
        assert hook["headers"] == {"Authorization": f"Bearer ${hooks.TOKEN_ENV}"}
        assert hook["allowedEnvVars"] == [hooks.TOKEN_ENV]
        assert hook["timeout"] <= 5


def _stop_check(repo: Path, again: bool) -> str:
    """What a build's own Stop hook says when its agent ends a turn in
    ``repo`` (``again``: the agent already sent back once)."""
    (_, group) = hooks.settings("http://app", commit=True)["hooks"]["Stop"]
    ((hook,),) = [group["hooks"]]
    assert hook["type"] == "command"
    event = {"hook_event_name": "Stop", "cwd": str(repo), "stop_hook_active": again}
    done = subprocess.run(
        hook["command"],
        shell=True,
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def test_a_build_ending_its_turn_with_work_not_committed_is_sent_back_once(
    tmp_path: Path,
) -> None:
    """A Push sends commits: an agent that would stop with its work not
    committed is told to commit it, once; a second stop goes through,
    so one that cannot (its checks fail) says why instead of looping."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert _stop_check(repo, again=False) == ""

    (repo / "NOTES.md").write_text("built")

    said = json.loads(_stop_check(repo, again=False))
    assert said == {"decision": "block", "reason": protocol.COMMIT_ASKED}
    assert _stop_check(repo, again=True) == ""


def test_the_cli_prints_the_settings_for_an_app() -> None:
    result = invoke(["runner", "hooks", "--url", "http://webserver:8000"])

    assert result.exit_code == 0
    assert json.loads(result.output) == hooks.settings("http://webserver:8000")
