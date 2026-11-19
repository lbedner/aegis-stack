"""The runner component, and its dev service: ``runner run`` in a container
beside the app, answering what the app asks of a coding agent.

Dev only, like deploy-agent: it acts with the developer's agent login and
their repositories. It sees the host's home at the same path, so a repo
path, the agent's user skills and other repos on disk read as they do on
the host. Its keys come from its own optional env file, never ``.env``,
where the app refuses a key it does not know; nor does ``.env`` reach it,
so the app's secrets stay out of the agent's environment.
"""

from pathlib import Path
from typing import Any

import pytest

from aegis.constants import ComponentNames
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES
from tests.core._compose import entrypoint_calls, load, render


def _runner(**overrides: Any) -> dict[str, Any] | None:
    rendered = render("docker-compose.dev.yml.jinja", **overrides)
    return load(rendered)["services"].get("runner")


def test_it_is_a_component_meetings_requires() -> None:
    """The queue and its runner are the component's; meetings asks runs of
    it, as it joins calls through the browser component. The dev service is
    the component's agent: its container and logs show on the runner's
    Overseer page, which its health check gives it."""
    assert COMPONENTS[ComponentNames.RUNNER].agents == ["runner"]
    meetings = SERVICES["meetings"]
    assert ComponentNames.RUNNER in meetings.required_components
    assert not meetings.agents


def test_its_health_check_is_registered_where_it_is() -> None:
    """Overseer lists what has a health check: the runner's is registered at
    startup, in a stack that has it."""
    startup = render(
        "app/components/backend/startup/component_health.py.jinja", include_runner=True
    )
    assert "register_health_check(ComponentName.RUNNER, check_runner_health)" in startup
    assert "check_runner_health" not in render(
        "app/components/backend/startup/component_health.py.jinja", include_runner=False
    )


def test_updating_a_meetings_stack_from_before_it_brings_it(tmp_path: Path) -> None:
    """A project generated before the runner was a component has meetings
    on disk and no answer for the runner: an update reads that it has it,
    or it would render meetings without what it now imports. Only that:
    what else a part requires is not switched on behind a project's back."""
    from aegis.commands.update import _detect_existing_features

    (tmp_path / "app/services/meetings").mkdir(parents=True)
    (tmp_path / "app/components/web_frontend").mkdir(parents=True)

    detected = _detect_existing_features(tmp_path)

    assert detected["include_runner"] is True
    assert "include_deploy" not in detected  # htmx requires it; never inferred


def test_a_stack_with_it_runs_one_in_dev_only() -> None:
    runner = _runner(include_runner=True)

    assert runner is not None
    assert runner["profiles"] == ["dev"]
    assert runner["command"] == ["runner"]
    assert runner["healthcheck"] == {"disable": True}  # it serves nothing
    assert _runner(include_runner=False) is None


def test_it_sees_the_hosts_home_where_the_host_does() -> None:
    runner = _runner(include_runner=True)

    assert runner is not None
    assert "${HOME}:${HOME}" in runner["volumes"]
    assert "HOME=${HOME}" in runner["environment"]


def test_its_keys_come_from_its_own_env_file() -> None:
    runner = _runner(include_runner=True)

    assert runner is not None
    assert runner["env_file"] == [{"path": ".env.runner", "required": False}]


def test_with_meetings_it_still_reads_the_file_from_before_the_component() -> None:
    """A meetings stack kept its runner's keys in .env.meetings-runner; the
    older file goes first, so .env.runner wins once it exists."""
    runner = _runner(include_runner=True, include_meetings=True)

    assert runner is not None
    assert runner["env_file"] == [
        {"path": ".env.meetings-runner", "required": False},
        {"path": ".env.runner", "required": False},
    ]


def test_the_entrypoint_runs_it_and_idles_without_a_token() -> None:
    with_it = render("scripts/entrypoint.sh.jinja", include_runner=True)
    without = render("scripts/entrypoint.sh.jinja", include_runner=False)

    assert '"runner" ]' in with_it
    assert "RUNNER_TOKEN" in with_it
    assert '"runner" ]' not in without


def _ran(tmp_path: Path, env: dict[str, str], meetings: bool = False) -> str:
    """The arguments the entrypoint hands ``python`` for the ``runner``
    command, in a container with ``env`` set."""
    (call,) = entrypoint_calls(
        tmp_path,
        ["runner"],
        {"RUNNER_URL": "http://webserver:8000", **env},
        include_runner=True,
        include_meetings=meetings,
    )
    assert call["cmd"] == "python" and call["exec"]
    return str(call["args"])


@pytest.mark.parametrize(
    ("meetings", "token"),
    [
        (False, "RUNNER_TOKEN"),
        # A meetings stack from before the component: its env file's name.
        (True, "MEETINGS_RUNNER_TOKEN"),
    ],
)
def test_with_no_command_set_it_runs_claude_in_a_session_and_asks_what_it_cost(
    tmp_path: Path, meetings: bool, token: str
) -> None:
    """The default commands reach the runner whole, ``{prompt}`` and all:
    the one that starts a session and the one that resumes it, each given
    the hooks that say what the run is doing (``{hooks}``, the runner's to
    fill in). The docs show them as they are."""
    args = _ran(tmp_path, {token: "rnr_test"}, meetings)

    how = "--output-format json --permission-mode plan --settings {hooks}"
    command = f"claude -p {{prompt}} --session-id {{session}} {how}"
    resume = f"claude -p {{prompt}} --resume {{session}} {how}"
    assert f"--command {command} --resume-command {resume}" in args
    docs = Path("docs/components/runner.md").read_text()
    assert command in docs and resume in docs


def test_a_command_of_its_own_resumes_only_as_it_is_told_to(tmp_path: Path) -> None:
    """The default resume form is Claude's: a runner given another command
    resumes nothing unless it is told how."""
    own = {"RUNNER_TOKEN": "rnr_test", "RUNNER_COMMAND": "codex exec {prompt}"}
    (tmp_path / "alone").mkdir()
    (tmp_path / "told").mkdir()

    alone = _ran(tmp_path / "alone", own)
    told = _ran(
        tmp_path / "told", {**own, "RUNNER_RESUME_COMMAND": "codex resume {session}"}
    )

    assert "--command codex exec {prompt}" in alone
    assert "--resume-command" not in alone
    assert "--resume-command codex resume {session}" in told


def test_it_keeps_worktrees_and_stops_commands_as_it_is_told(tmp_path: Path) -> None:
    env = {
        "RUNNER_TOKEN": "rnr_test",
        "RUNNER_WORKTREES": "/work/trees",
        "RUNNER_TIMEOUT": "3600",
    }

    args = _ran(tmp_path, env)

    assert "--worktrees /work/trees" in args and "--timeout 3600" in args


def test_make_build_builds_it_with_the_app() -> None:
    """Its image is the app's with git and Claude Code added: built beside
    the app's, or it keeps an old base after a dependency changes."""
    built = [
        line
        for line in render("Makefile.jinja", include_runner=True).splitlines()
        if line.strip().endswith("build webserver runner")
    ]
    assert built
    assert "build webserver runner" not in render(
        "Makefile.jinja", include_runner=False
    )
