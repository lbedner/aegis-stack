"""``aegis deploy`` tells the app on the server what only the deployer knows.

The app records a new build itself when it starts; who deployed it, from
where, its health, the backup taken before it and a rollback come from the
deployer, through ``deploy record`` run in the webserver container. Writing
the record never decides a deploy's outcome.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from aegis.commands import deploy

BUILD = "a1b2c3d"


@pytest.fixture
def with_history(tmp_path: Path) -> Path:
    (tmp_path / "app" / "cli").mkdir(parents=True)
    (tmp_path / "app" / "cli" / "deploy_cli.py").write_text("")
    return tmp_path


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []

    def run(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        sent.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(deploy, "_run_remote_capture", run)
    monkeypatch.setattr(deploy, "_deployer", lambda root: "Ada <ada@example.org>")
    monkeypatch.setattr(deploy.socket, "gethostname", lambda: "ada-laptop")
    return sent


def test_the_record_runs_in_the_webserver_with_what_the_deployer_knows(
    with_history: Path, remote: list[str]
) -> None:
    deploy._record_deploy(
        with_history, "h", "u", "/opt/app", BUILD, health="passed", backup="T1"
    )

    (command,) = remote
    assert "exec -T webserver python -m app.cli.main deploy record" in command
    assert f"--build {BUILD}" in command
    assert "--by 'Ada <ada@example.org>'" in command
    assert "--from ada-laptop" in command
    assert "--health passed" in command
    assert "--backup T1" in command
    assert "--rolled-back-to" not in command


def test_a_rollback_lets_the_app_name_the_build_now_running(
    with_history: Path, remote: list[str]
) -> None:
    deploy._record_deploy(
        with_history, "h", "u", "/opt/app", BUILD, health="failed", rolled_back=True
    )

    assert "--rolled-back" in remote[0]


def test_container_commands_quote_every_argument() -> None:
    """``deploy-exec`` and the deploy record build their command one way."""
    command = deploy._exec_command(
        "/opt/app", "webserver", ["python", "-m", "app.cli.main", "--by", "Ada <a@b>"]
    )

    assert command == (
        f"{deploy._compose_prefix('/opt/app')} exec -T webserver "
        "python -m app.cli.main --by 'Ada <a@b>'"
    )


def test_a_manual_rollback_records_the_build_it_rolled_back_from(
    with_history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    def run(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        sent.append(command)
        live = "badbeef\n" if "BUILD_ID" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout=live, stderr="")

    monkeypatch.setattr(deploy, "_run_remote_capture", run)
    monkeypatch.setattr(deploy, "_run_remote", lambda h, u, c: None)
    monkeypatch.setattr(deploy, "_rollback_to_backup", lambda *a, **k: True)
    monkeypatch.setattr(deploy, "_deployer", lambda root: None)
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=b"", stderr=b""),
    )
    monkeypatch.setattr(
        deploy,
        "_load_deploy_config",
        lambda p: {"server": {"host": "h", "user": "u", "path": "/opt/app"}},
    )

    deploy.deploy_rollback_command(project_path=str(with_history), backup="T1")

    (record,) = [c for c in sent if "deploy record" in c]
    assert "--build badbeef" in record and "--rolled-back" in record


def test_a_project_without_deploy_history_is_left_alone(
    tmp_path: Path, remote: list[str]
) -> None:
    deploy._record_deploy(tmp_path, "h", "u", "/opt/app", BUILD, health="passed")

    assert remote == []


def test_a_failed_record_warns_and_the_deploy_stands(
    with_history: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            command, 1, stdout="", stderr="no such table"
        )

    monkeypatch.setattr(deploy, "_run_remote_capture", fail)
    monkeypatch.setattr(deploy, "_deployer", lambda root: None)

    deploy._record_deploy(with_history, "h", "u", "/opt/app", BUILD, health="passed")

    assert "no such table" in capsys.readouterr().out


def test_upload_env_returns_the_build_it_stamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dirty tree's id carries the time, so it is computed once."""
    stamped: list[str] = []
    monkeypatch.setattr(deploy, "_build_id", lambda root: "a1b2c3d-dirty-1")
    monkeypatch.setattr(
        deploy, "_run_remote", lambda h, u, command: stamped.append(command)
    )

    build: Any = deploy._upload_env(tmp_path, "h", "u", "/opt/app")

    assert build == "a1b2c3d-dirty-1"
    assert "BUILD_ID=a1b2c3d-dirty-1" in stamped[0]


@pytest.mark.parametrize(
    ("code", "stdout", "expected"),
    [(0, "9f8e7d6\n", "9f8e7d6"), (0, "", None), (1, "9f8e7d6\n", None)],
)
def test_the_live_build_is_read_from_the_server_env(
    monkeypatch: pytest.MonkeyPatch, code: int, stdout: str, expected: str | None
) -> None:
    monkeypatch.setattr(
        deploy,
        "_run_remote_capture",
        lambda h, u, command: subprocess.CompletedProcess(command, code, stdout, ""),
    )

    assert deploy._live_build("h", "u", "/opt/app") == expected


# ---------------------------------------------------------------------------
# Found on the live run: BUILD_ID never reached the app, and the record named
# aegis's own init identity as the deployer.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "before",
    [
        "A=1\n# a comment with no newline",
        "A=1\nBUILD_ID=old\n",
        "",
    ],
)
def test_the_build_id_stamp_lands_on_its_own_line(tmp_path: Path, before: str) -> None:
    """The generated .env ends without a newline, so an appended
    ``BUILD_ID=`` joined the last comment and was never set."""
    env = tmp_path / ".env"
    env.write_text(before)

    subprocess.run(
        ["bash", "-c", deploy._stamp_build_id_command(str(env), "a1b2c3d")],
        check=True,
    )

    lines = env.read_text().splitlines()
    assert lines.count("BUILD_ID=a1b2c3d") == 1
    assert not [
        line for line in lines if "BUILD_ID=" in line and line != "BUILD_ID=a1b2c3d"
    ]


def _repo_with_identity(path: Path, name: str, email: str) -> Path:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for key, value in (("user.name", name), ("user.email", email)):
        subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
    return path


@pytest.fixture
def global_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Ada\n\temail = ada@example.org\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)


@pytest.mark.usefixtures("global_identity")
def test_the_deployer_is_you_not_the_identity_init_committed_as(tmp_path: Path) -> None:
    from aegis.core.copier_manager import AEGIS_GIT_EMAIL, AEGIS_GIT_NAME

    project = _repo_with_identity(tmp_path / "app", AEGIS_GIT_NAME, AEGIS_GIT_EMAIL)

    assert deploy._deployer(project) == "Ada <ada@example.org>"


@pytest.mark.usefixtures("global_identity")
def test_a_project_identity_you_set_yourself_wins(tmp_path: Path) -> None:
    project = _repo_with_identity(tmp_path / "app", "Ada at Work", "ada@work.example")

    assert deploy._deployer(project) == "Ada at Work <ada@work.example>"


@pytest.mark.parametrize(
    "components",
    [{}, {"include_database": True, "include_ingress": True, "include_deploy": True}],
)
def test_the_generated_env_ends_with_a_newline(components: dict[str, Any]) -> None:
    """A line appended to it (``echo X >> .env``) must start a line of its own."""
    from jinja2 import Environment, FileSystemLoader

    from aegis.core.component_files import get_copier_defaults, get_template_path

    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    context = {**get_copier_defaults(), "project_slug": "demo", **components}
    rendered = env.get_template("{{ project_slug }}/.env.example.jinja").render(context)

    assert rendered.endswith("\n")
