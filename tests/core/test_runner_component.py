"""The runner component, and its dev service: ``runner run`` in a container
beside the app, answering what the app asks of a coding agent.

Dev only, like deploy-agent: it acts with the developer's agent login and
their repositories. It sees the host's home at the same path, so a repo
path, the agent's user skills and other repos on disk read as they do on
the host. Its keys come from its own optional env file, never ``.env``,
where the app refuses a key it does not know; nor does ``.env`` reach it,
so the app's secrets stay out of the agent's environment.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from aegis.constants import ComponentNames
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES
from tests.core._compose import load, render


def _runner(**overrides: Any) -> dict[str, Any] | None:
    rendered = render("docker-compose.dev.yml.jinja", **overrides)
    return load(rendered)["services"].get("runner")


def test_it_is_a_component_meetings_requires() -> None:
    """The queue and its runner are the component's; meetings asks runs of
    it, as it joins calls through the browser component. The dev service is
    nobody's agent while the runner has no Overseer page to show it on."""
    assert not COMPONENTS[ComponentNames.RUNNER].agents
    meetings = SERVICES["meetings"]
    assert ComponentNames.RUNNER in meetings.required_components
    assert not meetings.agents


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


@pytest.mark.parametrize(
    ("meetings", "token"),
    [
        (False, "RUNNER_TOKEN"),
        # A meetings stack from before the component: its env file's name.
        (True, "MEETINGS_RUNNER_TOKEN"),
    ],
)
def test_with_no_command_set_it_runs_claude_on_the_prompt(
    tmp_path: Path, meetings: bool, token: str
) -> None:
    """The default command reaches the runner whole, ``{prompt}`` and all."""
    script = tmp_path / "entrypoint.sh"
    script.write_text(
        render(
            "scripts/entrypoint.sh.jinja",
            include_runner=True,
            include_meetings=meetings,
        )
    )
    stub = tmp_path / "python"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    stub.chmod(0o755)

    ran = subprocess.run(
        ["bash", str(script), "runner"],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "DOCKER_CONTAINER": "1",
            "RUNNER_URL": "http://webserver:8000",
            token: "rnr_test",
        },
        capture_output=True,
        text=True,
        check=True,
    )

    args = ran.stdout.splitlines()
    command = args[args.index("--command") + 1]
    assert command == "claude -p {prompt} --permission-mode plan"


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
