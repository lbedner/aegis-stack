"""The dev stack's meetings-runner service: ``meetings runner`` in a
container beside the app, answering what Overseer asks of a coding agent.

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

from tests.core._compose import load, render


def _runner(**overrides: Any) -> dict[str, Any] | None:
    rendered = render("docker-compose.dev.yml.jinja", **overrides)
    return load(rendered)["services"].get("meetings-runner")


def test_a_meetings_stack_runs_one_in_dev_only() -> None:
    runner = _runner(include_meetings=True, include_worker=True)

    assert runner is not None
    assert runner["profiles"] == ["dev"]
    assert runner["command"] == ["meetings-runner"]
    assert runner["healthcheck"] == {"disable": True}  # it serves nothing
    assert _runner(include_meetings=False) is None


def test_it_sees_the_hosts_home_where_the_host_does() -> None:
    runner = _runner(include_meetings=True, include_worker=True)

    assert runner is not None
    assert "${HOME}:${HOME}" in runner["volumes"]
    assert "HOME=${HOME}" in runner["environment"]


def test_its_keys_come_from_its_own_env_file() -> None:
    runner = _runner(include_meetings=True, include_worker=True)

    assert runner is not None
    assert runner["env_file"] == [{"path": ".env.meetings-runner", "required": False}]


def test_the_entrypoint_runs_it_and_idles_without_a_token() -> None:
    with_meetings = render("scripts/entrypoint.sh.jinja", include_meetings=True)
    without = render("scripts/entrypoint.sh.jinja", include_meetings=False)

    assert '"meetings-runner" ]' in with_meetings
    assert "MEETINGS_RUNNER_TOKEN" in with_meetings
    assert '"meetings-runner" ]' not in without


def test_with_no_command_set_it_runs_claude_on_the_prompt(tmp_path: Path) -> None:
    """The default command reaches the runner whole, ``{prompt}`` and all."""
    script = tmp_path / "entrypoint.sh"
    script.write_text(render("scripts/entrypoint.sh.jinja", include_meetings=True))
    stub = tmp_path / "python"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    stub.chmod(0o755)

    ran = subprocess.run(
        ["bash", str(script), "meetings-runner"],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "DOCKER_CONTAINER": "1",
            "MEETINGS_RUNNER_TOKEN": "mrt_test",
            "MEETINGS_RUNNER_URL": "http://webserver:8000",
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
        for line in render("Makefile.jinja", include_meetings=True).splitlines()
        if line.strip().endswith("build webserver meetings-runner")
    ]
    assert built
    assert "meetings-runner" not in render("Makefile.jinja", include_meetings=False)
