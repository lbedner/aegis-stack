"""Unit tests for pure helpers in ``aegis.commands.deploy``.

Pins regressions caught during the deploy-cd-setup PR review:
- ``_detect_github_repo`` must accept repo names containing dots (``next.js``)
  and strip optional ``.git`` / trailing slashes across SSH and HTTPS forms.
- ``_render_deploy_workflow`` must conditionally inject the tag-push
  trigger, and run on a bare runner.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml

from aegis import __version__
from aegis.commands import deploy as deploy_mod
from aegis.commands.deploy import (
    ROLLING_ROLLOUT_TIMEOUT_DEFAULT,
    _create_backup,
    _detect_github_repo,
    _is_neon_database,
    _render_deploy_workflow,
    _rollback_to_backup,
    _rolling_health_verdict,
    _rolling_inspect_health_command,
    _rolling_new_services,
    _rolling_scale_command,
)
from aegis.config.defaults import version_to_git_tag


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


def test_the_workflows_deploy_step_runs_a_command_deploy_accepts() -> None:
    """It once passed ``--yes``, which ``aegis deploy`` has no option for:
    every CD run failed before deploying."""
    from typer.testing import CliRunner

    from aegis.__main__ import app

    step = _step(_render_deploy_workflow(on_tag=False), "Deploy")["run"]
    step = step.split(" aegis ", 1)[1]
    result = CliRunner().invoke(app, [*step.split(), "--help"])
    assert result.exit_code == 0, result.output


def _step(workflow: str, name: str) -> dict[str, Any]:
    """The workflow's step called ``name``."""
    steps = yaml.safe_load(workflow)["jobs"]["deploy"]["steps"]
    return next(s for s in steps if s.get("name") == name)


def test_the_runner_writes_the_deploy_config_it_is_given() -> None:
    """``.aegis/`` is gitignored, so a checkout has no deploy config; the
    one ``deploy-cd-setup`` pushed comes back from its secret."""
    step = _step(_render_deploy_workflow(on_tag=False), "Write the deploy config")
    assert step["env"]["DEPLOY_CONFIG"] == "${{ secrets.DEPLOY_CONFIG }}"
    assert ".aegis/deploy.yml" in step["run"]


@pytest.mark.parametrize(
    ("answers", "ref"),
    [
        ("_commit: 0f096b58ef46\n", "0f096b58ef46"),
        ("_commit: 'v0.16.1'\n", "v0.16.1"),
        ("_commit: None\n", version_to_git_tag(__version__)),
        ("project_slug: app\n", version_to_git_tag(__version__)),
    ],
)
def test_the_runner_deploys_with_the_aegis_stack_the_project_is_on(
    tmp_path: Path, answers: str, ref: str
) -> None:
    """A runner has no ``aegis`` (it is no project dependency), so the CLI
    comes from the commit ``aegis update`` last recorded, else the release
    that wrote the workflow."""
    workflow = _render_deploy_workflow(on_tag=False)
    (tmp_path / ".copier-answers.yml").write_text(answers)
    output = tmp_path / "github_output"
    subprocess.run(
        [
            "bash",
            "-c",
            _step(workflow, "Resolve the aegis-stack this project is on")["run"],
        ],
        cwd=tmp_path,
        env={"GITHUB_OUTPUT": str(output), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    assert output.read_text() == f"ref={ref}\n"
    deploy = _step(workflow, "Deploy")["run"]
    assert deploy.startswith(
        "uvx --from git+https://github.com/lbedner/aegis-stack@${{ steps.aegis.outputs.ref }} aegis deploy"
    )
    assert "uv run" not in workflow and "uv sync" not in workflow
    # The CLI's Python is its own; the project's pin once broke it (3.14).
    assert "uv python install" not in workflow


@pytest.mark.parametrize("pushed", [True, False])
def test_the_runner_ships_the_env_it_is_given(tmp_path: Path, pushed: bool) -> None:
    """The env ``deploy-cd-env`` pushed comes back as ``.env.deploy``, byte
    for byte (quotes, comments and all), for ``aegis deploy`` to ship. Never
    pushed, there is no file, so the server keeps its own ``.env``."""
    env = 'SECRET_KEY="a b#c"\n# note\nexport TOKEN=x=y\n'
    step = _step(_render_deploy_workflow(on_tag=False), "Write the deploy env")
    assert step["env"]["DEPLOY_ENV"] == "${{ secrets.DEPLOY_ENV }}"
    subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env={"DEPLOY_ENV": env if pushed else "", "PATH": "/usr/bin:/bin"},
        check=True,
    )
    written = tmp_path / ".env.deploy"
    if pushed:
        assert written.read_text().rstrip("\n") == env.rstrip("\n")
    else:
        assert not written.exists()


def test_two_deploys_never_run_at_once() -> None:
    concurrency = yaml.safe_load(_render_deploy_workflow(on_tag=False))["concurrency"]
    assert concurrency == {"group": "deploy", "cancel-in-progress": False}


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


class TestWorkingTreeRsync:
    """The deploy sync must delete, and must not delete the irreplaceable.

    ``aegis deploy`` rsynced without ``--delete``, so a file removed from the
    project lived on the server forever and got baked into the image built
    from that directory. It bit aegis-pulse in prod: a surviving
    ``llm_vendor.py`` re-registered a model the migration had just dropped,
    the startup hook recreated its table, mapper configuration then failed
    for every mapper, and three seeds silently did not run - while the
    health check passed and the deploy reported success (aegis-stack#1130).

    These run the real rsync between two local directories: a wrong exclude
    spelling would satisfy an assertion about argv and still destroy a
    production Let's Encrypt store.
    """

    def _tree(self, tmp_path: Path) -> tuple[Path, Path]:
        source = tmp_path / "project"
        server = tmp_path / "server"
        (source / "app").mkdir(parents=True)
        (source / "traefik").mkdir()
        (source / "app" / "kept.py").write_text("kept\n")
        (source / "traefik" / "traefik.yml").write_text("entryPoints: [websecure]\n")

        (server / "app").mkdir(parents=True)
        (server / "traefik" / "acme").mkdir(parents=True)
        (server / "app" / "kept.py").write_text("kept\n")
        # Removed from the project three versions ago; still importable here.
        (server / "app" / "llm_vendor.py").write_text("class LLMVendor: ...\n")
        (server / "traefik" / "traefik.yml").write_text("stale\n")
        (server / "traefik" / "acme" / "acme.json").write_text("CERTIFICATES\n")
        (server / ".env").write_text("SECRET=production\n")
        return source, server

    def _sync(self, source: Path, server: Path) -> None:
        command = deploy_mod._working_tree_rsync(source, f"{server}/")
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_a_file_removed_from_the_project_is_removed_from_the_server(
        self, tmp_path: Path
    ) -> None:
        source, server = self._tree(tmp_path)
        self._sync(source, server)
        assert not (server / "app" / "llm_vendor.py").exists()
        assert (server / "app" / "kept.py").exists()

    def test_the_letsencrypt_store_survives(self, tmp_path: Path) -> None:
        """Deleting it forces re-issuance and can hit Let's Encrypt rate limits."""
        source, server = self._tree(tmp_path)
        self._sync(source, server)
        assert (
            server / "traefik" / "acme" / "acme.json"
        ).read_text() == "CERTIFICATES\n"

    def test_traefik_config_still_syncs(self, tmp_path: Path) -> None:
        """Protecting the cert store must not freeze the config beside it."""
        source, server = self._tree(tmp_path)
        self._sync(source, server)
        assert (
            server / "traefik" / "traefik.yml"
        ).read_text() == "entryPoints: [websecure]\n"

    def test_the_server_env_survives(self, tmp_path: Path) -> None:
        source, server = self._tree(tmp_path)
        self._sync(source, server)
        assert (server / ".env").read_text() == "SECRET=production\n"


class TestTrackedTree:
    """A deploy ships what git tracks, not whatever sits in the directory.

    The rsync excludes named ``.env`` exactly, so ``.env.backup-*`` (a copy
    of the production secrets), scratch notes and local dumps all went to
    the server (aegis-stack#1557).
    """

    def _project(self, tmp_path: Path) -> Path:
        source = tmp_path / "project"
        (source / "app").mkdir(parents=True)
        (source / "app" / "kept.py").write_text("kept\n")
        (source / "app" / "gone.py").write_text("gone\n")
        subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "app"], check=True)
        (source / "app" / "gone.py").unlink()  # deleted, not yet committed
        (source / ".env.backup-20260911").write_text("SECRET=production\n")
        (source / "notes.md").write_text("scratch\n")
        return source

    def test_only_tracked_files_reach_the_server(self, tmp_path: Path) -> None:
        source = self._project(tmp_path)
        server = tmp_path / "server"
        server.mkdir()
        # Leaked by an earlier deploy: the next one takes it back off.
        (server / ".env.backup-20260101").write_text("SECRET=old\n")
        (server / ".env").write_text("SECRET=production\n")

        with deploy_mod._tracked_tree(source) as shipped:
            command = deploy_mod._working_tree_rsync(shipped, f"{server}/")
            result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

        on_server = sorted(
            str(p.relative_to(server)) for p in server.rglob("*") if p.is_file()
        )
        assert on_server == [".env", "app/kept.py"]

    def test_a_tree_outside_git_ships_as_it_is(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text("x\n")
        with deploy_mod._tracked_tree(tmp_path) as shipped:
            assert shipped == tmp_path

    def test_a_repo_tracking_nothing_ships_the_tree(self, tmp_path: Path) -> None:
        """An empty shipped tree would ``--delete`` the server's code."""
        (tmp_path / "app.py").write_text("x\n")
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
        with deploy_mod._tracked_tree(tmp_path) as shipped:
            assert shipped == tmp_path


def test_both_deploy_paths_sync_the_same_way() -> None:
    """Standard and rolling deploy built identical rsync argv by hand.

    They drifted apart the moment one of them gained ``--delete`` and the
    other did not, which is the whole reason this is one function.
    """
    source = Path("/tmp/project")
    command = deploy_mod._working_tree_rsync(source, "user@host:/srv/app/")
    assert "--delete" in command
    assert command[-2:] == [f"{source}/", "user@host:/srv/app/"]


# ---------------------------------------------------------------------------
# BUILD_ID: the deployed commit, stamped into the server's .env.
#
# The generated app namespaces its cached payloads by this value, so a
# deploy has to move it or new code keeps serving what the old code built
# until the TTL expires.
# ---------------------------------------------------------------------------


def _git_commit(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], check=True)
    (path / "a.txt").write_text("one")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "one"], check=True)


def test_build_id_is_the_short_commit(tmp_path: Path) -> None:
    _git_commit(tmp_path)

    expected = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert deploy_mod._build_id(tmp_path) == expected


def test_build_id_marks_a_dirty_tree(tmp_path: Path) -> None:
    """Uncommitted changes ship code no commit describes, so that code
    gets its own namespace instead of reusing the clean commit's."""
    _git_commit(tmp_path)
    clean = deploy_mod._build_id(tmp_path)

    (tmp_path / "a.txt").write_text("two")
    dirty = deploy_mod._build_id(tmp_path)

    assert dirty != clean
    assert dirty.startswith(f"{clean}-dirty-")


def test_build_id_without_a_repo_is_not_fatal(tmp_path: Path) -> None:
    """A deploy from an exported tree still has to produce a namespace."""
    assert deploy_mod._build_id(tmp_path) == "unknown"


def test_upload_env_stamps_the_build_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_commit(tmp_path)
    (tmp_path / ".env.deploy").write_text("FOO=bar\n")
    remote: list[str] = []
    monkeypatch.setattr(
        deploy_mod,
        "_run_remote",
        lambda host, user, command: remote.append(command),
    )
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):  # type: ignore[no-untyped-def]
        # Let the git calls in ``_build_id`` run for real; stub the scp.
        if cmd and cmd[0] == "git":
            return real_run(cmd, *a, **k)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(deploy_mod.subprocess, "run", fake_run)

    deploy_mod._upload_env(tmp_path, "h", "u", "/opt/app")

    assert len(remote) == 1
    command = remote[0]
    # Replacing, not appending, on its own line: run for real against a file
    # in tests/cli/test_deploy_record.py (the stamp's own test).
    assert command == deploy_mod._stamp_env_command(
        "/opt/app/.env", {"BUILD_ID": deploy_mod._build_id(tmp_path)}
    )
    remote.clear()
    (tmp_path / ".aegis").mkdir()
    (tmp_path / ".aegis" / "deploy.yml").write_text(
        "domain: app.example.com\nacme_email: ops@example.org\n"
        "admin_ip_allowlist: 203.0.113.9/32\n"
    )
    deploy_mod._upload_env(tmp_path, "h", "u", "/opt/app")
    assert remote == [
        deploy_mod._stamp_env_command(
            "/opt/app/.env",
            {
                "BUILD_ID": deploy_mod._build_id(tmp_path),
                "DOMAIN": "app.example.com",
                "ACME_EMAIL": "ops@example.org",
                "ADMIN_IP_ALLOWLIST": "203.0.113.9/32",
            },
        )
    ]


def test_upload_env_stamps_even_without_a_local_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server may already hold its own ``.env``; the stamp still has to
    land or that deploy serves stale payloads."""
    _git_commit(tmp_path)
    remote: list[str] = []
    monkeypatch.setattr(
        deploy_mod,
        "_run_remote",
        lambda host, user, command: remote.append(command),
    )

    deploy_mod._upload_env(tmp_path, "h", "u", "/opt/app")

    assert len(remote) == 1
    assert "BUILD_ID=" in remote[0]


def _fake_compose_listing(defined: str, known: str, calls: list[str]):
    def _fake(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        calls.append(command)
        stdout = defined if "config --services" in command else known
        return subprocess.CompletedProcess([], returncode=0, stdout=stdout, stderr="")

    return _fake


def test_rolling_new_services_lists_services_without_a_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        deploy_mod,
        "_run_remote_capture",
        _fake_compose_listing(
            "webserver\npostgres\nsocket-proxy\nmigrate\n",
            "webserver\npostgres\nmigrate\n",
            calls,
        ),
    )

    assert _rolling_new_services("h", "u", "/srv/app") == ["socket-proxy"]
    # ``--all`` keeps an exited one-shot service (migrate) from counting as new.
    assert any("ps --services --all" in c for c in calls)
    assert any("--profile prod config --services" in c for c in calls)


def test_rolling_new_services_is_empty_when_compose_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], returncode=1, stdout="x\n", stderr="")

    monkeypatch.setattr(deploy_mod, "_run_remote_capture", failing)

    assert _rolling_new_services("h", "u", "/srv/app") == []


def test_rolling_deploy_starts_services_the_release_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        deploy_mod.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], returncode=0),
    )
    monkeypatch.setattr(deploy_mod, "_upload_env", lambda *a, **k: "build1")
    monkeypatch.setattr(
        deploy_mod, "_rolling_running_services", lambda *a, **k: {"webserver"}
    )
    monkeypatch.setattr(deploy_mod, "_rolling_swap_webserver", lambda *a, **k: True)
    monkeypatch.setattr(
        deploy_mod, "_rolling_new_services", lambda *a, **k: ["socket-proxy"]
    )
    monkeypatch.setattr(deploy_mod, "_run_remote", _record_remote(calls))
    monkeypatch.setattr(deploy_mod, "_record_deploy", lambda *a, **k: None)
    monkeypatch.setattr(deploy_mod, "_prune_docker", lambda *a, **k: None)

    deploy_mod._run_rolling_deploy(
        "h",
        "u",
        "/srv/app",
        tmp_path,
        build=False,
        health_check=False,
        health_cfg={},
        health_command="",
        drain_timeout=1,
        rollout_timeout=1,
    )

    assert any(c.endswith("up -d --no-deps socket-proxy") for c in calls)


# ---------------------------------------------------------------------------
# The env a deploy ships: never one that puts the app online open.
# ---------------------------------------------------------------------------

SAFE = "APP_ENV=prod\nSECRET_KEY=k3y\n"


@pytest.mark.parametrize(
    ("env", "unsafe"),
    [
        (SAFE, []),
        (SAFE + "AUTH_ENABLED=true\n", []),
        (SAFE + "AUTH_ENABLED=false\n", ["AUTH_ENABLED"]),
        (SAFE + "AUTH_ENABLED=0\n", ["AUTH_ENABLED"]),
        ("APP_ENV=dev\nSECRET_KEY=k3y\n", ["APP_ENV"]),
        ("SECRET_KEY=k3y\n", ["APP_ENV"]),  # unset: the app's default, dev
        ("APP_ENV=prod\nSECRET_KEY=\n", ["SECRET_KEY"]),
        ("AUTH_ENABLED=false\n", ["AUTH_ENABLED", "APP_ENV", "SECRET_KEY"]),
    ],
)
def test_the_settings_that_would_ship_the_app_open_are_named(
    tmp_path: Path, env: str, unsafe: list[str]
) -> None:
    (tmp_path / ".copier-answers.yml").write_text("include_auth: true\n")
    (tmp_path / ".env.deploy").write_text(env)
    (tmp_path / ".env").write_text("AUTH_ENABLED=false\n")  # local, not shipped
    assert deploy_mod.unsafe_settings(tmp_path) == unsafe


def test_sign_in_off_is_only_unsafe_where_there_is_sign_in(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("include_auth: false\n")
    (tmp_path / ".env.deploy").write_text(SAFE + "AUTH_ENABLED=false\n")
    assert deploy_mod.unsafe_settings(tmp_path) == []


def test_without_an_env_file_the_servers_own_is_kept(tmp_path: Path) -> None:
    assert deploy_mod.unsafe_settings(tmp_path) == []


def test_deploy_refuses_an_open_env_before_touching_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from aegis.__main__ import app

    (tmp_path / ".aegis").mkdir()
    server = {"host": "203.0.113.7", "user": "root", "path": "/opt/my-app"}
    (tmp_path / ".aegis" / "deploy.yml").write_text(yaml.safe_dump({"server": server}))
    (tmp_path / ".env").write_text("APP_ENV=dev\nAUTH_ENABLED=false\n")

    def touched(*_a: object, **_k: object) -> None:
        raise AssertionError("the server was reached")

    monkeypatch.setattr(deploy_mod, "_check_disk_space", touched)
    monkeypatch.setattr(deploy_mod, "_run_remote", touched)
    result = CliRunner().invoke(app, ["deploy", "--project-path", str(tmp_path)])
    assert result.exit_code == 1
    assert "AUTH_ENABLED" in result.output and ".env" in result.output


# ---------------------------------------------------------------------------
# A rolling deploy backs up, and brings the database up to the new code
# before anything restarts on it (aegis-stack#1789).
# ---------------------------------------------------------------------------


def _quiet_rolling(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], fail: str = ""
) -> None:
    """A rolling deploy with every remote step recorded in ``calls``; the
    one whose command holds ``fail`` fails."""

    def remote(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        calls.append(command)
        failed = bool(fail) and fail in command
        return subprocess.CompletedProcess([], returncode=int(failed), stdout="")

    monkeypatch.setattr(
        deploy_mod.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], returncode=0),
    )
    monkeypatch.setattr(deploy_mod, "_upload_env", lambda *a, **k: "build1")
    monkeypatch.setattr(
        deploy_mod,
        "_rolling_running_services",
        lambda *a, **k: {"webserver", "scheduler", "worker-system"},
    )
    monkeypatch.setattr(deploy_mod, "_rolling_wait_for_drain", lambda *a, **k: True)
    monkeypatch.setattr(
        deploy_mod,
        "_rolling_swap_webserver",
        lambda *a, **k: calls.append("swap") or True,
    )
    monkeypatch.setattr(deploy_mod, "_rolling_new_services", lambda *a, **k: [])
    monkeypatch.setattr(deploy_mod, "_run_remote", remote)
    monkeypatch.setattr(deploy_mod, "_record_deploy", lambda *a, **k: None)
    monkeypatch.setattr(deploy_mod, "_prune_docker", lambda *a, **k: None)


def _roll(tmp_path: Path, **kwargs: Any) -> None:
    deploy_mod._run_rolling_deploy(
        "h",
        "u",
        "/srv/app",
        tmp_path,
        build=True,
        health_check=False,
        health_cfg={},
        health_command="",
        drain_timeout=1,
        rollout_timeout=1,
        **kwargs,
    )


def test_a_rolling_deploy_backs_up_then_migrates_before_anything_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _quiet_rolling(monkeypatch, calls)

    _roll(tmp_path, backup=lambda: calls.append("backup") or "2026-10-21_000000")

    migrate = "run --rm --no-deps --entrypoint python webserver -c"
    marks = ("backup", " build webserver", migrate, "--force-recreate", "swap")
    order = [next(i for i, c in enumerate(calls) if mark in c) for mark in marks]
    assert order == sorted(order)


def test_a_failed_migration_restarts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old code keeps serving: nothing has been swapped."""
    calls: list[str] = []
    _quiet_rolling(monkeypatch, calls, fail="run --rm")

    with pytest.raises(typer.Exit):
        _roll(tmp_path)

    assert not [c for c in calls if "--force-recreate" in c or c == "swap"]


def _boot_step(root: Path, gaps: str | None) -> int:
    """Run ``ROLLING_MIGRATE`` against a project whose boot module reports
    ``gaps`` (None: a project without one); its exit code."""
    if gaps is not None:
        module = root / "app/components/backend/startup"
        module.mkdir(parents=True)
        for part in (
            root / "app",
            root / "app/components",
            root / "app/components/backend",
            module,
        ):
            (part / "__init__.py").touch()
        (module / "database_init.py").write_text(
            "async def startup_database_init() -> None: ...\n"
            f"def schema_gaps() -> dict: return {gaps}\n"
        )
    return subprocess.run(
        [sys.executable, "-c", deploy_mod.ROLLING_MIGRATE],
        cwd=root,
        env={"PYTHONPATH": str(root)},
        capture_output=True,
    ).returncode


@pytest.mark.parametrize(
    ("gaps", "code"),
    [(None, 0), ("{}", 0), ("{'ledger': {'payee_key'}}", 1)],
)
def test_the_boot_step_fails_when_the_database_lacks_what_the_code_reads(
    tmp_path: Path, gaps: str | None, code: int
) -> None:
    """The boot step logs a failed migration and carries on, as a boot
    must; the rolling deploy asks ``schema_gaps`` after it, and stops."""
    assert _boot_step(tmp_path, gaps) == code


def _cd_project(root: Path, ci: dict[str, Any] | None, **extra: Any) -> None:
    """A project's ``.aegis/deploy.yml``, with ``ci`` as setup leaves it (or
    ``None``: setup never ran)."""
    config: dict[str, Any] = {
        "server": {"host": "203.0.113.7", "user": "root", "path": "/opt/app"},
        **extra,
    }
    if ci is not None:
        config["ci"] = ci
    (root / ".aegis").mkdir()
    (root / ".aegis" / "deploy.yml").write_text(yaml.safe_dump(config))


WIRED = {"github": {"repo": "acme/app"}}


def _record_gh_pushes(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, str]]:
    """Fakes the gh layer; each pushed secret's name -> (value, repo)."""
    pushed: dict[str, tuple[str, str]] = {}

    def push(name: str, value: str, repo: str) -> subprocess.CompletedProcess:
        pushed[name] = (value, repo)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    def push_file(name: str, path: Path, repo: str) -> subprocess.CompletedProcess:
        return push(name, path.read_text(), repo)

    monkeypatch.setattr(deploy_mod, "_check_gh_cli", lambda: None)
    monkeypatch.setattr(deploy_mod, "_set_gh_secret", push)
    monkeypatch.setattr(deploy_mod, "_set_gh_secret_from_file", push_file)
    return pushed


def test_setup_pushes_the_deploy_config_it_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner deploys from the secret, so it is the file, ``ci`` block
    and all, not a copy of some of its fields."""
    _cd_project(tmp_path, None, domain="app.example.com")
    pushed = _record_gh_pushes(monkeypatch)
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(deploy_mod, "_list_gh_secrets", lambda repo: set())
    monkeypatch.setattr(deploy_mod, "_install_pubkey_on_server", lambda *a: done)

    deploy_mod.deploy_cd_setup_command(
        project_path=str(tmp_path),
        repo="acme/app",
        on_tag=False,
        force=False,
        dry_run=False,
        keep_key=None,
    )

    saved = (tmp_path / ".aegis" / "deploy.yml").read_text()
    assert pushed["DEPLOY_CONFIG"] == (saved, "acme/app")
    assert yaml.safe_load(saved)["ci"]["github"]["repo"] == "acme/app"
    assert {"DEPLOY_SSH_KEY", "DEPLOY_HOST", "DEPLOY_USER"} <= set(pushed)


@pytest.mark.parametrize("env_file", [None, "prod.env"])
def test_env_push_sends_the_env_file_whole_to_the_repo_setup_wired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_file: str | None
) -> None:
    """``.env.deploy`` (or the file it is pointed at), whole, as one secret
    (on stdin, never in argv), to the repo ``deploy-cd-setup`` recorded."""
    _cd_project(tmp_path, WIRED)
    (tmp_path / ".env.deploy").write_text(SAFE + "# deploy\n")
    (tmp_path / "prod.env").write_text(SAFE + "# other\n")
    (tmp_path / ".env").write_text("AUTH_ENABLED=false\n")
    pushed = _record_gh_pushes(monkeypatch)

    deploy_mod.deploy_cd_env_command(
        project_path=str(tmp_path),
        env_file=str(tmp_path / env_file) if env_file else None,
    )

    sent = (tmp_path / (env_file or ".env.deploy")).read_text()
    assert pushed == {"DEPLOY_ENV": (sent, "acme/app")}


@pytest.mark.parametrize(
    ("ci", "files"),
    [
        # The dev .env is never pushed in .env.deploy's place.
        pytest.param(WIRED, {".env": SAFE}, id="no-env-deploy"),
        pytest.param(None, {".env.deploy": SAFE}, id="setup-never-ran"),
        pytest.param({"github": None}, {".env.deploy": SAFE}, id="ci-github-null"),
        # What a deploy would refuse is refused before it reaches GitHub.
        pytest.param(WIRED, {".env.deploy": "APP_ENV=dev\n"}, id="open-env"),
    ],
)
def test_env_push_refuses_rather_than_guess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ci: dict[str, Any] | None,
    files: dict[str, str],
) -> None:
    _cd_project(tmp_path, ci)
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    pushed = _record_gh_pushes(monkeypatch)

    with pytest.raises(typer.Exit):
        deploy_mod.deploy_cd_env_command(project_path=str(tmp_path), env_file=None)

    assert pushed == {}
