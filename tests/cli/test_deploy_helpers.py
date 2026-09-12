"""Unit tests for pure helpers in ``aegis.commands.deploy``.

Pins regressions caught during the deploy-cd-setup PR review:
- ``_detect_github_repo`` must accept repo names containing dots (``next.js``)
  and strip optional ``.git`` / trailing slashes across SSH and HTTPS forms.
- ``_render_deploy_workflow`` must conditionally inject the
  ``uv python install`` step and the tag-push trigger.
- ``_project_python_minor`` must extract major.minor from a
  ``requires-python`` constraint and degrade gracefully when missing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import typer
import yaml

from aegis.commands import deploy as deploy_mod
from aegis.commands.deploy import (
    ROLLING_ROLLOUT_TIMEOUT_DEFAULT,
    _create_backup,
    _detect_github_repo,
    _is_neon_database,
    _project_python_minor,
    _render_deploy_workflow,
    _rollback_to_backup,
    _rolling_health_verdict,
    _rolling_inspect_health_command,
    _rolling_scale_command,
)


def _git_init_with_origin(path: Path, remote: str) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "remote", "add", "origin", remote], check=True
    )


@pytest.mark.parametrize(
    "remote,expected",
    [
        ("git@github.com:lbedner/aegis-stack.git", "lbedner/aegis-stack"),
        ("https://github.com/lbedner/aegis-stack.git", "lbedner/aegis-stack"),
        ("https://github.com/lbedner/aegis-stack", "lbedner/aegis-stack"),
        ("https://github.com/foo/bar/", "foo/bar"),
    ],
)
def test_detect_github_repo_parses_common_forms(
    tmp_path: Path, remote: str, expected: str
) -> None:
    _git_init_with_origin(tmp_path, remote)
    assert _detect_github_repo(tmp_path) == expected


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:vercel/next.js.git",
        "https://github.com/vercel/next.js.git",
        "https://github.com/vercel/next.js",
    ],
)
def test_detect_github_repo_handles_dotted_repo_names(
    tmp_path: Path, remote: str
) -> None:
    _git_init_with_origin(tmp_path, remote)
    assert _detect_github_repo(tmp_path) == "vercel/next.js"


def test_detect_github_repo_returns_none_for_non_github(tmp_path: Path) -> None:
    _git_init_with_origin(tmp_path, "git@gitlab.com:foo/bar.git")
    assert _detect_github_repo(tmp_path) is None


def test_detect_github_repo_returns_none_when_not_a_repo(tmp_path: Path) -> None:
    assert _detect_github_repo(tmp_path) is None


def test_render_deploy_workflow_default_is_workflow_dispatch_only() -> None:
    out = _render_deploy_workflow(on_tag=False)
    yaml.safe_load(out)  # validate structure
    # YAML 1.1 parses bare "on:" as boolean True, so we assert on text.
    assert "workflow_dispatch:" in out
    assert "push:" not in out


def test_render_deploy_workflow_on_tag_adds_v_star_trigger() -> None:
    out = _render_deploy_workflow(on_tag=True)
    yaml.safe_load(out)
    assert "workflow_dispatch:" in out
    assert "push:" in out
    assert "- 'v*'" in out


def test_render_deploy_workflow_pins_python_when_version_provided() -> None:
    out = _render_deploy_workflow(on_tag=False, python_version="3.13")
    yaml.safe_load(out)  # must remain valid YAML
    assert "uv python install 3.13" in out


def test_render_deploy_workflow_omits_python_step_when_none() -> None:
    out = _render_deploy_workflow(on_tag=False, python_version=None)
    yaml.safe_load(out)
    assert "uv python install" not in out


def test_render_deploy_workflow_references_required_secrets() -> None:
    out = _render_deploy_workflow(on_tag=False)
    assert "${{ secrets.DEPLOY_SSH_KEY }}" in out
    assert "${{ secrets.DEPLOY_HOST }}" in out


def test_rolling_scale_command_builds_scale_up() -> None:
    # Brings up a 2nd webserver replica alongside the old one without
    # recreating the old container or touching dependencies, so HTTP keeps
    # flowing through Traefik during the swap.
    cmd = _rolling_scale_command("/srv/app", 2)
    assert "cd /srv/app &&" in cmd
    assert "-f docker-compose.yml -f docker-compose.prod.yml" in cmd
    assert "--no-deps" in cmd
    assert "--no-recreate" in cmd
    assert "--scale webserver=2" in cmd
    assert cmd.rstrip().endswith("webserver")


def test_rolling_scale_command_quotes_deploy_path() -> None:
    cmd = _rolling_scale_command("/srv/my app", 1)
    assert "cd '/srv/my app'" in cmd
    assert "--scale webserver=1" in cmd


def test_rolling_inspect_health_command_reads_health_status() -> None:
    cmd = _rolling_inspect_health_command("abc123def456")
    assert "docker inspect" in cmd
    # Falls back to container State.Status when no HEALTHCHECK is defined.
    assert ".State.Health.Status" in cmd
    assert ".State.Status" in cmd
    assert "abc123def456" in cmd


def test_rolling_inspect_health_command_quotes_container_id() -> None:
    cmd = _rolling_inspect_health_command("weird id")
    assert "'weird id'" in cmd


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("healthy", "healthy"),
        ('"healthy"', "healthy"),
        ("running", "healthy"),
        ("unhealthy", "unhealthy"),
        ("exited", "unhealthy"),
        ("dead", "unhealthy"),
        ("starting", "starting"),
        ("created", "starting"),
        ("", "starting"),
        ("<no value>", "starting"),
    ],
)
def test_rolling_health_verdict_maps_status(raw: str, expected: str) -> None:
    # The container's own HEALTHCHECK drives the outcome: only an explicit
    # unhealthy/exited verdict rolls back; anything still settling keeps
    # polling, so a slow-but-healthy boot is never killed by a wall clock.
    assert _rolling_health_verdict(raw) == expected


def test_rolling_rollout_timeout_default_is_generous() -> None:
    # A long runaway-guard ceiling so the container's own HEALTHCHECK
    # budget (start_period + retries x interval) decides the outcome, not
    # a short wall clock.
    assert ROLLING_ROLLOUT_TIMEOUT_DEFAULT >= 600


def test_project_python_minor_parses_requires_python(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.13,<3.15"\n'
    )
    assert _project_python_minor(tmp_path) == "3.13"


def test_project_python_minor_returns_none_for_missing_pyproject(
    tmp_path: Path,
) -> None:
    assert _project_python_minor(tmp_path) is None


def test_project_python_minor_returns_none_when_constraint_missing(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n')
    assert _project_python_minor(tmp_path) is None


def test_project_python_minor_returns_none_for_malformed_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("this is = not :: valid toml [")
    assert _project_python_minor(tmp_path) is None


# --- Neon-aware deploy (issue #765) -----------------------------------------


def _write_answers(path: Path, provider: str) -> None:
    (path / ".copier-answers.yml").write_text(
        f"database_engine: postgres\npostgres_provider: {provider}\n"
    )


def test_is_neon_database_true_for_neon_provider(tmp_path: Path) -> None:
    _write_answers(tmp_path, "neon")
    assert _is_neon_database(str(tmp_path)) is True


def test_is_neon_database_false_for_container_provider(tmp_path: Path) -> None:
    _write_answers(tmp_path, "container")
    assert _is_neon_database(str(tmp_path)) is False


def test_is_neon_database_false_when_answers_missing(tmp_path: Path) -> None:
    assert _is_neon_database(str(tmp_path)) is False


def test_is_neon_database_false_for_malformed_answers(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("{ not: valid: yaml")
    assert _is_neon_database(str(tmp_path)) is False


def _record_remote(calls: list[str]):
    def _fake(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        calls.append(command)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    return _fake


def test_create_backup_skips_local_pgdump_for_neon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(deploy_mod, "_run_remote_capture", _record_remote(calls))

    ts = _create_backup("h", "u", "/srv/app", include_db=True, neon=True)

    assert ts is not None
    assert not any("pg_dump" in c for c in calls), "neon backup must not run pg_dump"
    assert not any("ps postgres" in c for c in calls)


def test_create_backup_runs_pgdump_for_container_when_pg_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        calls.append(command)
        # Report the postgres service as present/running.
        stdout = "abc123\n" if "ps postgres" in command else ""
        return subprocess.CompletedProcess([], returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(deploy_mod, "_run_remote_capture", fake)

    _create_backup("h", "u", "/srv/app", include_db=True, neon=False)

    assert any("pg_dump" in c for c in calls), "container backup must run pg_dump"


def test_rollback_skips_db_restore_for_neon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(deploy_mod, "_run_remote_capture", _record_remote(calls))
    monkeypatch.setattr(deploy_mod, "_run_remote", _record_remote(calls))

    ok = _rollback_to_backup("h", "u", "/srv/app", "2026-01-01_000000", neon=True)

    assert ok is True
    assert not any("psql" in c for c in calls), "neon rollback must not run psql"
    assert not any("db_backup.sql" in c for c in calls)


class TestDeployExec:
    """``deploy-exec`` is the scriptable sibling of ``deploy-shell``: its
    whole value is that callers stop hand-assembling the compose-file
    chain (omitting it silently drops the prod overrides) and that a
    failing remote command fails the local one."""

    @staticmethod
    def _capture(monkeypatch: pytest.MonkeyPatch, returncode: int = 0) -> dict:
        seen: dict = {}

        def fake_run(argv, *args, **kwargs):
            seen["argv"] = argv
            seen["captured"] = bool(kwargs.get("capture_output"))
            return subprocess.CompletedProcess(argv, returncode)

        monkeypatch.setattr(deploy_mod.subprocess, "run", fake_run)
        monkeypatch.setattr(
            deploy_mod,
            "_load_deploy_config",
            lambda _p: {
                "server": {"host": "h", "user": "u", "path": "/opt/app"},
            },
        )
        return seen

    def test_sends_the_full_prod_compose_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)
        deploy_mod.deploy_exec_command(
            command=["alembic", "current"], service="webserver"
        )

        remote = seen["argv"][-1]
        assert "docker-compose.yml" in remote
        assert "docker-compose.prod.yml" in remote
        assert "--profile prod" in remote
        # -T, not a TTY: output has to stay pipeable.
        assert "exec -T webserver" in remote
        assert remote.endswith("alembic current")

    def test_quotes_each_argument(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An argument with spaces must arrive as one argument, not several."""
        seen = self._capture(monkeypatch)
        deploy_mod.deploy_exec_command(
            command=["echo", "two words"], service="webserver"
        )

        assert "'two words'" in seen["argv"][-1]

    def test_streams_rather_than_captures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = self._capture(monkeypatch)
        deploy_mod.deploy_exec_command(command=["ls"], service="webserver")

        assert seen["captured"] is False

    def test_propagates_the_remote_exit_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without this, a failed migration would look like a success to
        ``set -e`` and to CI."""
        self._capture(monkeypatch, returncode=3)
        with pytest.raises(typer.Exit) as exc:
            deploy_mod.deploy_exec_command(command=["false"], service="webserver")
        assert exc.value.exit_code == 3

    def test_success_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._capture(monkeypatch, returncode=0)
        deploy_mod.deploy_exec_command(command=["true"], service="webserver")

    def test_rejects_an_empty_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._capture(monkeypatch)
        with pytest.raises(typer.Exit):
            deploy_mod.deploy_exec_command(command=[], service="webserver")
