"""
Tests for shared post-generation tasks module.

These tests validate the post-generation task functions that are used
by both Cookiecutter hooks and Copier updaters.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from aegis.core.post_gen_tasks import (
    DependencyInstallationError,
    _truncate_stderr,
    cleanup_components,
    format_code,
    install_dependencies,
    run_migrations,
    run_post_generation_tasks,
    setup_env_file,
)


class TestTruncateStderr:
    """Test stderr truncation helper function."""

    def test_short_output_unchanged(self) -> None:
        """Test that short output is returned unchanged."""
        stderr = "line 1\nline 2\nline 3"
        result = _truncate_stderr(stderr)
        assert result == "line 1\nline 2\nline 3"

    def test_truncates_long_output(self) -> None:
        """Test that long output is truncated."""
        lines = [f"line {i}" for i in range(30)]
        stderr = "\n".join(lines)

        result = _truncate_stderr(stderr, max_lines=10)

        # Should have head + omitted message + tail
        result_lines = result.split("\n")
        assert len(result_lines) == 11  # 5 head + 1 omitted + 5 tail
        assert "omitted" in result_lines[5].lower()
        assert "20" in result_lines[5]  # 30 - 10 = 20 omitted

    def test_preserves_first_and_last_lines(self) -> None:
        """Test that first and last lines are preserved."""
        lines = [f"line {i}" for i in range(30)]
        stderr = "\n".join(lines)

        result = _truncate_stderr(stderr, max_lines=10)

        result_lines = result.split("\n")
        assert result_lines[0] == "line 0"
        assert result_lines[-1] == "line 29"

    def test_handles_empty_input(self) -> None:
        """Test handling of empty input."""
        result = _truncate_stderr("")
        assert result == ""

    def test_handles_single_line(self) -> None:
        """Test handling of single line input."""
        result = _truncate_stderr("single line")
        assert result == "single line"

    def test_strips_whitespace(self) -> None:
        """Test that leading/trailing whitespace is stripped."""
        result = _truncate_stderr("  line 1\nline 2  \n")
        assert result == "line 1\nline 2"


class TestInstallDependencies:
    """Test dependency installation task."""

    def test_successful_installation(self, tmp_path: Path) -> None:
        """Test successful dependency installation."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")

            result = install_dependencies(tmp_path)

            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0] == ["uv", "sync", "--all-extras"]
            assert args[1]["cwd"] == tmp_path
            assert "VIRTUAL_ENV" not in args[1]["env"]

    def test_relock_re_resolves_the_lockfile(self, tmp_path: Path) -> None:
        """#1019: a plain ``uv sync`` honours a stale ``uv.lock``, so an
        updated project kept year-old pins and ~80 phantom type errors.
        ``relock`` re-resolves against the updated pyproject."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")

            install_dependencies(tmp_path, relock=True)

            assert mock_run.call_args[0][0] == [
                "uv",
                "sync",
                "--all-extras",
                "--upgrade",
            ]

    def test_installation_failure(self, tmp_path: Path) -> None:
        """Test failed dependency installation."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="Installation error")

            result = install_dependencies(tmp_path)

            assert result is False

    def test_installation_timeout(self, tmp_path: Path) -> None:
        """Test dependency installation timeout."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("uv", 300)):
            result = install_dependencies(tmp_path)

            assert result is False

    def test_uv_not_found(self, tmp_path: Path) -> None:
        """Test when uv command is not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = install_dependencies(tmp_path)

            assert result is False

    def test_virtual_env_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that VIRTUAL_ENV is properly unset."""
        monkeypatch.setenv("VIRTUAL_ENV", "/some/venv")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")

            install_dependencies(tmp_path)

            args = mock_run.call_args
            assert "VIRTUAL_ENV" not in args[1]["env"]


class TestSetupEnvFile:
    """Test environment file setup task."""

    def test_creates_env_from_example(self, tmp_path: Path) -> None:
        """Test creating .env from .env.example."""
        env_example = tmp_path / ".env.example"
        env_example.write_text("DATABASE_URL=sqlite:///./data/app.db\n")

        result = setup_env_file(tmp_path)

        assert result is True
        env_file = tmp_path / ".env"
        assert env_file.exists()
        assert env_file.read_text() == "DATABASE_URL=sqlite:///./data/app.db\n"

    def test_env_already_exists(self, tmp_path: Path) -> None:
        """Test when .env already exists (should skip)."""
        env_example = tmp_path / ".env.example"
        env_example.write_text("EXAMPLE=value\n")
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=value\n")

        result = setup_env_file(tmp_path)

        assert result is True
        # Should not overwrite existing .env
        assert env_file.read_text() == "EXISTING=value\n"

    def test_no_example_file(self, tmp_path: Path) -> None:
        """Test when .env.example doesn't exist."""
        result = setup_env_file(tmp_path)

        assert result is False
        env_file = tmp_path / ".env"
        assert not env_file.exists()


class TestRunMigrations:
    """Test database migration task."""

    def test_skips_when_auth_disabled(self, tmp_path: Path) -> None:
        """Test migrations are skipped when auth not enabled."""
        result = run_migrations(tmp_path, include_migrations=False)

        assert result is True  # Success (no-op)

    def test_successful_migration(self, tmp_path: Path) -> None:
        """Test successful database migration."""
        # Create alembic config
        alembic_dir = tmp_path / "alembic"
        alembic_dir.mkdir()
        alembic_ini = alembic_dir / "alembic.ini"
        alembic_ini.write_text("[alembic]\n")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")

            result = run_migrations(tmp_path, include_migrations=True)

            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args
            # ``run_migrations`` now prepends ``--project <path>`` to isolate
            # the generated project's venv from the caller's (otherwise
            # ``aegis init``-then-migrate would grab the aegis-stack venv
            # and miss the project's own dependencies).
            assert args[0][0][0:4] == ["uv", "run", "--project", str(tmp_path)]
            assert args[0][0][4] == "alembic"
            assert "VIRTUAL_ENV" not in args[1]["env"]

    def test_missing_alembic_config(self, tmp_path: Path) -> None:
        """Test when alembic config doesn't exist."""
        result = run_migrations(tmp_path, include_migrations=True)

        assert result is False

    def test_migration_failure(self, tmp_path: Path) -> None:
        """Test failed migration."""
        alembic_dir = tmp_path / "alembic"
        alembic_dir.mkdir()
        alembic_ini = alembic_dir / "alembic.ini"
        alembic_ini.write_text("[alembic]\n")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="Migration error")

            result = run_migrations(tmp_path, include_migrations=True)

            assert result is False

    def test_creates_data_directory(self, tmp_path: Path) -> None:
        """Test that data directory is created."""
        alembic_dir = tmp_path / "alembic"
        alembic_dir.mkdir()
        alembic_ini = alembic_dir / "alembic.ini"
        alembic_ini.write_text("[alembic]\n")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")

            run_migrations(tmp_path, include_migrations=True)

            data_dir = tmp_path / "data"
            assert data_dir.exists()
            assert data_dir.is_dir()


class TestFormatCode:
    """Test code formatting task."""

    def test_successful_formatting(self, tmp_path: Path) -> None:
        """Test successful code formatting."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr="")

            result = format_code(tmp_path)

            assert result is True
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0] == ["make", "fix"]
            assert args[1]["cwd"] == tmp_path
            assert "VIRTUAL_ENV" not in args[1]["env"]

    def test_formatting_failure(self, tmp_path: Path) -> None:
        """Test formatting failure (non-critical)."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="Format error")

            result = format_code(tmp_path)

            assert result is False  # Reports failure but doesn't crash

    def test_make_not_found(self, tmp_path: Path) -> None:
        """Test when make command is not found."""
        with (
            patch("subprocess.run", side_effect=FileNotFoundError()),
            patch("aegis.core.template_cleanup.time.sleep"),
        ):
            result = format_code(tmp_path)

            assert result is False

    def test_formatting_timeout(self, tmp_path: Path) -> None:
        """Test formatting timeout."""
        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("make", 60)),
            patch("aegis.core.template_cleanup.time.sleep"),
        ):
            result = format_code(tmp_path)

            assert result is False

    def test_transient_spawn_failure_is_retried(self, tmp_path: Path) -> None:
        """A fork failure under load (EAGAIN) must be retried, not silently
        skipped: an unformatted project breaks the add-path byte-identity
        contract that regenerated shared files match init output."""
        with (
            patch(
                "subprocess.run",
                side_effect=[OSError("fork: EAGAIN"), Mock(returncode=0, stderr="")],
            ),
            patch("aegis.core.template_cleanup.time.sleep"),
        ):
            result = format_code(tmp_path)

            assert result is True

    def test_transient_timeout_is_retried(self, tmp_path: Path) -> None:
        """A timeout from a briefly starved machine is retried the same way."""
        with (
            patch(
                "subprocess.run",
                side_effect=[
                    subprocess.TimeoutExpired("make", 60),
                    Mock(returncode=0, stderr=""),
                ],
            ),
            patch("aegis.core.template_cleanup.time.sleep"),
        ):
            result = format_code(tmp_path)

            assert result is True


class TestRunPostGenerationTasks:
    """Test main post-generation task orchestrator."""

    def test_all_tasks_succeed(self, tmp_path: Path) -> None:
        """Test when all tasks succeed."""
        # Create minimal project structure
        env_example = tmp_path / ".env.example"
        env_example.write_text("TEST=value\n")

        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=True),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch("aegis.core.post_gen_tasks.run_migrations", return_value=True),
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            result = run_post_generation_tasks(tmp_path, include_migrations=False)

            assert result is True

    def test_dependency_install_failure(self, tmp_path: Path) -> None:
        """Test when dependency installation fails (critical - raises exception)."""
        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=False),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch("aegis.core.post_gen_tasks.run_migrations", return_value=True),
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            with pytest.raises(DependencyInstallationError) as exc_info:
                run_post_generation_tasks(tmp_path, include_migrations=False)

            assert str(tmp_path) in str(exc_info.value)

    def test_non_critical_failures_continue(self, tmp_path: Path) -> None:
        """Test that non-critical failures don't stop execution."""
        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=True),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=False),
            patch("aegis.core.post_gen_tasks.run_migrations", return_value=False),
            patch("aegis.core.post_gen_tasks.format_code", return_value=False),
        ):
            result = run_post_generation_tasks(tmp_path, include_migrations=True)

            assert result is True  # Deps succeeded, so overall success

    def test_migration_failure_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        """`run_migrations` returns False on a failed `alembic upgrade`, but
        the caller discarded that value, so nothing upstream could tell.
        `aegis update` then printed "completed successfully" over a
        migration that never applied (#1024). The overall return stays
        True (migrations are non-fatal, see the test above); the failure
        must be exposed through a separate channel the caller can read.
        """
        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=True),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch("aegis.core.post_gen_tasks.run_migrations", return_value=False),
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            outcome = run_post_generation_tasks(
                tmp_path, include_migrations=True, report=(report := {})
            )

            assert outcome is True
            assert report["migrations_ok"] is False

        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=True),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch("aegis.core.post_gen_tasks.run_migrations", return_value=True),
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            run_post_generation_tasks(
                tmp_path, include_migrations=True, report=(report := {})
            )
            assert report["migrations_ok"] is True

    def test_auth_migrations_triggered(self, tmp_path: Path) -> None:
        """Test that migrations run when auth is enabled."""
        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=True),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch("aegis.core.post_gen_tasks.run_migrations") as mock_migrations,
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            mock_migrations.return_value = True

            run_post_generation_tasks(tmp_path, include_migrations=True)

            mock_migrations.assert_called_once_with(tmp_path, True, None)

    def test_tasks_run_in_order(self, tmp_path: Path) -> None:
        """Test that tasks run in the correct order."""
        call_order = []

        def track_deps(
            path: Path, python_version: str | None = None, *, relock: bool = False
        ) -> bool:
            call_order.append("deps")
            return True

        def track_env(path: Path) -> bool:
            call_order.append("env")
            return True

        def track_migrations(
            path: Path, auth: bool, python_version: str | None = None
        ) -> bool:
            call_order.append("migrations")
            return True

        def track_format(path: Path) -> bool:
            call_order.append("format")
            return True

        with (
            patch(
                "aegis.core.post_gen_tasks.install_dependencies", side_effect=track_deps
            ),
            patch("aegis.core.post_gen_tasks.setup_env_file", side_effect=track_env),
            patch(
                "aegis.core.post_gen_tasks.run_migrations", side_effect=track_migrations
            ),
            patch("aegis.core.post_gen_tasks.format_code", side_effect=track_format),
        ):
            run_post_generation_tasks(tmp_path, include_migrations=True)

            assert call_order == ["deps", "env", "migrations", "format"]


class TestRevisionsDerivedInsideTheProjectVenv:
    """Revision files come from the models, so they are written after the
    venv exists and before ``alembic upgrade head`` applies them."""

    def test_revisions_run_between_install_and_migrate(self, tmp_path: Path) -> None:
        order: list[str] = []
        with (
            patch(
                "aegis.core.post_gen_tasks.install_dependencies",
                side_effect=lambda *_a, **_k: order.append("install") or True,
            ),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch(
                "aegis.core.post_gen_tasks.generate_revisions",
                side_effect=lambda *_a, **_k: order.append("revisions") or [],
            ) as gen,
            patch(
                "aegis.core.post_gen_tasks.run_migrations",
                side_effect=lambda *_a, **_k: order.append("migrate") or True,
            ),
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            run_post_generation_tasks(
                tmp_path,
                include_migrations=True,
                migration_services=["auth", "finance"],
                python_version="3.13",
            )
        assert order == ["install", "revisions", "migrate"]
        assert gen.call_args.args[:2] == (tmp_path, ["auth", "finance"])
        assert gen.call_args.kwargs.get("python_version") == "3.13"

    def test_no_services_means_no_revision_step(self, tmp_path: Path) -> None:
        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=True),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch("aegis.core.post_gen_tasks.generate_revisions") as gen,
            patch("aegis.core.post_gen_tasks.run_migrations", return_value=True),
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            run_post_generation_tasks(tmp_path, include_migrations=False)
        gen.assert_not_called()

    def test_generation_failure_is_reported_not_raised(self, tmp_path: Path) -> None:
        from aegis.core.migration_generator import MigrationGenerationError

        report: dict[str, bool] = {}
        with (
            patch("aegis.core.post_gen_tasks.install_dependencies", return_value=True),
            patch("aegis.core.post_gen_tasks.setup_env_file", return_value=True),
            patch(
                "aegis.core.post_gen_tasks.generate_revisions",
                side_effect=MigrationGenerationError("boom"),
            ),
            patch("aegis.core.post_gen_tasks.run_migrations", return_value=True) as mig,
            patch("aegis.core.post_gen_tasks.format_code", return_value=True),
        ):
            run_post_generation_tasks(
                tmp_path,
                include_migrations=True,
                migration_services=["auth"],
                report=report,
            )
        assert report["revisions_ok"] is False
        # the upgrade is skipped: a DB must not be stamped past revisions
        # that never landed
        assert mig.call_args.args[1] is False


class TestOllamaModeCleanup:
    """``ollama_mode: none`` must leave no Ollama file behind.

    Their importers are all jinja-gated, so the files ship dead rather than
    breaking the boot — but ``ollama_modal.py`` imports ``ollama_activity``,
    which renders empty in that mode, so the module cannot even import.
    """

    OLLAMA_FILES = (
        "app/components/frontend/dashboard/cards/ollama_card.py",
        "app/components/frontend/dashboard/modals/ollama_modal.py",
        "app/services/system/health_ollama.py",
        "app/services/ai/domains/llm/ollama.py",
        "app/services/ai/domains/llm/ollama_activity.py",
    )

    def _project(self, tmp_path: Path) -> Path:
        for rel in self.OLLAMA_FILES:
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")
        return tmp_path

    def _context(self, ollama_mode: str) -> dict[str, Any]:
        return {
            "include_ai": True,
            "include_frontend": True,
            "include_database": True,
            "ai_backend": "postgres",
            "ai_providers": "ollama",
            "ollama_mode": ollama_mode,
        }

    def test_none_removes_every_ollama_file(self, tmp_path: Path) -> None:
        project = self._project(tmp_path)
        cleanup_components(project, self._context("none"))
        left = [rel for rel in self.OLLAMA_FILES if (project / rel).exists()]
        assert not left, f"ollama_mode=none still ships: {left}"

    def test_host_keeps_them(self, tmp_path: Path) -> None:
        project = self._project(tmp_path)
        cleanup_components(project, self._context("host"))
        assert all((project / rel).exists() for rel in self.OLLAMA_FILES)


class TestTheFinalBannerTellsTheTruth:
    """A step that failed must not be followed by an unqualified success.

    Non-critical failures are meant to continue (see
    ``test_non_critical_failures_continue``), and they print their own
    warning as they happen. The run then ended with "Project ready to
    run!" regardless, which is the line the user acts on - and at ``init``
    nothing else reads the result at all, so a project with no revisions
    and an empty database was announced as ready.
    """

    def test_a_clean_run_still_says_ready(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from unittest.mock import patch

        import aegis.core.post_gen_tasks as pgt

        with (
            patch.object(pgt, "install_dependencies", return_value=True),
            patch.object(pgt, "setup_env_file", return_value=True),
            patch.object(pgt, "run_migrations", return_value=True),
            patch.object(pgt, "format_code", return_value=True),
            patch.object(pgt, "render_project_map", lambda *a, **k: None),
        ):
            run_post_generation_tasks(tmp_path, include_migrations=True)

        assert "ready to run" in capsys.readouterr().out.lower()

    def test_a_failed_step_replaces_the_success_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from unittest.mock import patch

        import aegis.core.post_gen_tasks as pgt

        with (
            patch.object(pgt, "install_dependencies", return_value=True),
            patch.object(pgt, "setup_env_file", return_value=True),
            patch.object(pgt, "run_migrations", return_value=False),
            patch.object(pgt, "format_code", return_value=True),
            patch.object(pgt, "render_project_map", lambda *a, **k: None),
        ):
            run_post_generation_tasks(tmp_path, include_migrations=True)

        out = capsys.readouterr().out.lower()
        assert "ready to run" not in out
        assert "did not finish" in out

    def test_the_report_carries_every_step(self, tmp_path: Path) -> None:
        """The caller reads the detail here, not from the return value."""
        from unittest.mock import patch

        import aegis.core.post_gen_tasks as pgt

        report: dict[str, bool] = {}
        with (
            patch.object(pgt, "install_dependencies", return_value=True),
            patch.object(pgt, "setup_env_file", return_value=False),
            patch.object(pgt, "run_migrations", return_value=True),
            patch.object(pgt, "format_code", return_value=False),
            patch.object(pgt, "render_project_map", lambda *a, **k: None),
        ):
            run_post_generation_tasks(tmp_path, include_migrations=True, report=report)

        assert report["env_ok"] is False
        assert report["format_ok"] is False
        assert report["migrations_ok"] is True
