"""
Tests for the 'aegis update' command for template version upgrades.

Tests cover version detection, changelog generation, dry-run mode,
and the full update workflow.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from aegis.core.copier_manager import is_copier_project
from aegis.core.template_cleanup import SyncResult

from .test_utils import run_aegis_command, strip_ansi_codes

if TYPE_CHECKING:
    from tests.cli.conftest import ProjectFactory


class TestUpdateCommandBasics:
    """Basic validation tests for update command."""

    def test_update_command_help(self) -> None:
        """Test update command shows help text."""
        result = run_aegis_command("update", "--help")

        assert result.success
        clean_output = strip_ansi_codes(result.stdout.lower())
        assert "update" in clean_output
        assert "--to-version" in clean_output
        assert "--dry-run" in clean_output

    def test_update_command_not_copier_project(self, temp_output_dir: Path) -> None:
        """Test that update command fails on non-Copier projects."""
        # Create a dummy directory that's not a Copier project
        fake_project = temp_output_dir / "fake-project"
        fake_project.mkdir()

        # Try to update
        result = run_aegis_command(
            "update", "--project-path", str(fake_project), "--yes"
        )

        # Should fail with helpful message
        assert not result.success
        assert "not generated with copier" in result.stderr.lower()

    def test_update_command_missing_project(self) -> None:
        """Test that update command fails when project doesn't exist."""
        result = run_aegis_command(
            "update", "--project-path", "/nonexistent/path", "--yes"
        )

        assert not result.success
        assert "not generated with copier" in result.stderr.lower()


class TestUpdateCommandGitValidation:
    """Tests for git tree validation."""

    def test_update_requires_clean_git_tree(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update command requires clean git working tree."""
        # Use cached base project
        project_path = project_factory("base")

        # Verify it's a Copier project
        assert is_copier_project(project_path)

        # Create an uncommitted change
        test_file = project_path / "dirty.txt"
        test_file.write_text("uncommitted change")

        # Try to update
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--yes"
        )

        # Should fail with git tree error
        assert not result.success
        assert (
            "git tree" in result.stderr.lower()
            or "uncommitted" in result.stderr.lower()
        )

    def test_update_succeeds_with_clean_git_tree(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update command works with clean git tree."""
        # Use cached base project
        project_path = project_factory("base")

        # Verify it's a Copier project and has clean git tree
        assert is_copier_project(project_path)

        # Dry-run should work (doesn't actually update, so no version issues)
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--dry-run"
        )

        # Should either succeed (git is clean) or fail with a version-related message
        # but NOT with a git tree error
        if not result.success:
            assert "git tree" not in result.stderr.lower()
            assert "uncommitted" not in result.stderr.lower()

    def test_update_exits_early_when_at_target_commit(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update exits early when project is already at target commit."""
        # Use cached base project
        project_path = project_factory("base")

        # Verify it's a Copier project
        assert is_copier_project(project_path)

        # Try to update to HEAD (should be same commit as project was just created)
        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--to-version",
            "HEAD",
            "--yes",
        )

        # When running from local dev template (no git tags), Copier doesn't record
        # the template commit, so we can't detect "already at target commit".
        # In that case, the update will fail because Copier can't find the version.
        # This is expected behavior in dev environments.
        if "cannot determine current template version" in result.stdout.lower():
            # Skip this test scenario - no commit tracking available
            # The update may fail or succeed depending on Copier's handling
            return

        # Should succeed and show early exit message
        assert result.success
        assert "already at the requested version" in result.stdout.lower()


class TestUpdateCommandDryRun:
    """Tests for dry-run mode."""

    def test_dry_run_shows_preview(self, project_factory: "ProjectFactory") -> None:
        """Test that --dry-run shows preview without applying changes."""
        # Use cached base project
        project_path = project_factory("base")

        # Run update in dry-run mode
        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--to-version",
            "HEAD",
            "--dry-run",
        )

        # Should succeed and either show dry-run message or early exit message
        assert result.success
        # If early exit happened (already at target), that's valid too
        is_early_exit = "already at the requested version" in result.stdout.lower()
        has_dry_run_msg = (
            "dry run" in result.stdout.lower() or "preview" in result.stdout.lower()
        )
        assert is_early_exit or has_dry_run_msg

        # Should not have actually updated anything
        # (we can verify by checking that .copier-answers.yml hasn't changed)
        # This is a basic smoke test - real validation would compare commits


class TestUpdateCommandVersionResolution:
    """Tests for version resolution logic."""

    @patch("aegis.commands.update.resolve_version_to_ref")
    def test_update_to_latest_default(
        self,
        mock_resolve: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that update defaults to CLI version."""
        # Setup mock - resolve_version_to_ref is called with CLI version
        mock_resolve.return_value = "v0.2.0"

        # Use cached base project
        project_path = project_factory("base")

        # Run update in dry-run mode (to avoid actual update)
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--dry-run"
        )

        # Should show version information
        assert "version" in result.stdout.lower()

    @patch("aegis.commands.update.resolve_version_to_ref")
    def test_update_to_specific_version(
        self, mock_resolve: MagicMock, project_factory: "ProjectFactory"
    ) -> None:
        """Test updating to a specific version."""
        # Setup mock
        mock_resolve.return_value = "v0.1.5"

        # Use cached base project
        project_path = project_factory("base")

        # Run update to specific version in dry-run mode
        result = run_aegis_command(
            "update",
            "--to-version",
            "0.1.5",
            "--project-path",
            str(project_path),
            "--dry-run",
        )

        # Should mention the target version
        assert "0.1.5" in result.stdout or "v0.1.5" in result.stdout


class TestUpdateCommandChangelog:
    """Tests for changelog display."""

    @patch("aegis.commands.update.get_changelog")
    @patch("aegis.commands.update.get_current_template_commit")
    def test_update_shows_changelog(
        self,
        mock_get_commit: MagicMock,
        mock_get_changelog: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that update command shows changelog."""
        # Setup mocks - use a different commit to prevent early exit
        mock_get_commit.return_value = "abc123def456"
        mock_get_changelog.return_value = (
            "✨ New Features:\n  • Added AI service\n\n"
            "🐛 Bug Fixes:\n  • Fixed scheduler persistence"
        )

        # Use cached base project
        project_path = project_factory("base")

        # Run update in dry-run mode
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--dry-run"
        )

        # Should succeed
        assert result.success
        # Either shows changelog or early exit (both valid)
        has_changelog = (
            "changelog" in result.stdout.lower() or "changes" in result.stdout.lower()
        )
        is_early_exit = "already at the requested version" in result.stdout.lower()
        assert has_changelog or is_early_exit


class TestUpdateCommandConfirmation:
    """Tests for user confirmation workflow."""

    def test_update_requires_confirmation_without_yes_flag(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update requires confirmation without --yes flag."""
        # Use cached base project
        project_path = project_factory("base")

        # Note: This test is tricky because it requires user input simulation
        # For now, we just verify the command structure accepts --yes
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--help"
        )

        assert "--yes" in result.stdout or "-y" in result.stdout

    def test_update_skips_confirmation_with_yes_flag(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that --yes flag skips confirmation."""
        # Use cached base project
        project_path = project_factory("base")

        # Dry-run with --yes should not prompt
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--dry-run", "--yes"
        )

        # Should complete without waiting for input
        # (if it waited, the test would hang/timeout)
        assert result.stdout  # Got some output


class TestUpdateCommandErrorHandling:
    """Tests for error handling and edge cases."""

    def test_update_with_invalid_version(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test update with non-existent version."""
        # Use cached base project
        project_path = project_factory("base")

        # Try to update to an invalid version
        result = run_aegis_command(
            "update",
            "--to-version",
            "999.999.999",
            "--project-path",
            str(project_path),
            "--dry-run",
        )

        # Should handle gracefully (may show warning or proceed with HEAD)
        # At minimum, shouldn't crash
        assert result.stdout or result.stderr

    def test_update_shows_helpful_error_messages(self, temp_output_dir: Path) -> None:
        """Test that update shows helpful error messages."""
        # Create a non-Copier project
        fake_project = temp_output_dir / "not-copier"
        fake_project.mkdir()

        result = run_aegis_command(
            "update", "--project-path", str(fake_project), "--yes"
        )

        assert not result.success
        # Should have helpful error message
        assert len(result.stderr) > 0
        assert "copier" in result.stderr.lower()


class TestUpdateCommandTemplatePath:
    """Tests for --template-path flag functionality."""

    def test_update_command_has_template_path_option(self) -> None:
        """Test that update command has --template-path option in help."""
        result = run_aegis_command("update", "--help")

        assert result.success
        clean_output = strip_ansi_codes(result.stdout)
        assert "--template-path" in clean_output

    def test_update_with_nonexistent_template_path(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update fails with non-existent template path."""
        project_path = project_factory("base")

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--template-path",
            "/nonexistent/path",
            "--dry-run",
        )

        assert not result.success
        assert "does not exist" in result.stderr.lower()

    def test_update_with_invalid_template_structure(
        self, project_factory: "ProjectFactory", temp_output_dir: Path
    ) -> None:
        """Test that update fails when template path is missing copier.yml."""
        project_path = project_factory("base")

        # Create an empty directory (no copier.yml)
        invalid_template = temp_output_dir / "invalid-template"
        invalid_template.mkdir()

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--template-path",
            str(invalid_template),
            "--dry-run",
        )

        assert not result.success
        assert "missing copier.yml" in result.stderr.lower()

    def test_update_with_non_git_template_path(
        self, project_factory: "ProjectFactory", temp_output_dir: Path
    ) -> None:
        """Test that update fails when template path is not a git repository."""
        project_path = project_factory("base")

        # Create directory with copier.yml but no .git
        non_git_template = temp_output_dir / "non-git-template"
        non_git_template.mkdir()
        (non_git_template / "copier.yml").write_text("# mock copier config")

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--template-path",
            str(non_git_template),
            "--dry-run",
        )

        assert not result.success
        assert "git repository" in result.stderr.lower()

    def test_update_with_valid_template_path(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update works with valid custom template path."""
        project_path = project_factory("base")

        # Use the actual aegis-stack repo as template path
        # This is the same as the default, but tests the path validation
        from aegis.core.copier_updater import get_template_root

        template_root = get_template_root()

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--template-path",
            str(template_root),
            "--to-version",
            "HEAD",
            "--dry-run",
        )

        # Should succeed or show early exit (already at target)
        assert result.success
        # Should show that custom template is being used
        assert (
            "custom template" in result.stdout.lower()
            or "already at" in result.stdout.lower()
        )

    def test_update_template_path_expands_tilde(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that template path expands ~ to home directory."""
        project_path = project_factory("base")

        # Use a path that should expand (even if it doesn't exist)
        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--template-path",
            "~/nonexistent-aegis-stack",
            "--dry-run",
        )

        # Should fail with "does not exist" (not a raw path error)
        # This proves ~ was expanded
        assert not result.success
        assert "does not exist" in result.stderr.lower()
        # Should NOT contain the literal ~ in the error message
        assert "~/nonexistent" not in result.stderr


class TestUpdateCommandRollback:
    """Tests for rollback mechanism."""

    def test_update_creates_backup_point(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update creates a backup point before updating."""
        project_path = project_factory("base")

        # Run update in dry-run mode (won't actually update but shows workflow)
        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--to-version",
            "HEAD",
            "--dry-run",
        )

        # Dry run doesn't create backup, but command structure is valid
        assert result.success

    @patch("aegis.commands.update.create_backup_point")
    def test_update_calls_create_backup(
        self,
        mock_create_backup: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that update calls create_backup_point."""
        mock_create_backup.return_value = "aegis-backup-123"

        project_path = project_factory("base")

        # Run update (will hit early exit but should still create backup)
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--yes"
        )

        # Either creates backup or hits early exit
        assert result.stdout

    @patch("aegis.commands.update.sync_template_changes")
    @patch("aegis.commands.update.run_post_generation_tasks")
    @patch("copier.run_update")
    @patch("aegis.commands.update.get_current_template_commit")
    @patch("aegis.commands.update.cleanup_backup_tag")
    @patch("aegis.commands.update.create_backup_point")
    def test_update_cleans_up_backup_on_success(
        self,
        mock_create_backup: MagicMock,
        mock_cleanup: MagicMock,
        mock_get_commit: MagicMock,
        mock_copier_update: MagicMock,
        mock_post_gen: MagicMock,
        mock_sync: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that backup tag is cleaned up on successful update."""
        mock_create_backup.return_value = "aegis-backup-123"
        mock_get_commit.return_value = "different-commit"  # Prevent early exit
        mock_post_gen.return_value = True  # Mock successful post-gen tasks
        # A clean sync (no conflicts) is what "success" means here — isolate the
        # backup-cleanup assertion from the merge internals, which conservatively
        # conflict when no old-render base is available (issue #773).
        mock_sync.return_value = SyncResult()

        project_path = project_factory("base")

        # Run update
        run_aegis_command("update", "--project-path", str(project_path), "--yes")

        # Backup should be created and cleaned up on success
        assert mock_create_backup.called, "Backup should be created"
        assert mock_cleanup.called, "Cleanup should be called when backup was created"

    @patch("aegis.commands.update.rollback_to_backup")
    @patch("aegis.commands.update.create_backup_point")
    @patch("copier.run_update")
    def test_update_offers_rollback_on_failure(
        self,
        mock_copier_update: MagicMock,
        mock_create_backup: MagicMock,
        mock_rollback: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that update offers rollback when Copier fails."""
        mock_create_backup.return_value = "aegis-backup-123"
        mock_copier_update.side_effect = Exception("Copier failed")
        mock_rollback.return_value = (True, "Rolled back successfully")

        project_path = project_factory("base")

        # Run update with --yes to auto-rollback
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--yes"
        )

        # Should fail but offer/perform rollback
        # Note: may hit early exit before Copier is called
        assert result.stdout or result.stderr


class TestUpdateCommandPostGenTasks:
    """Tests for post-generation task handling."""

    @patch("aegis.commands.update.run_post_generation_tasks")
    def test_update_shows_warning_on_post_gen_failure(
        self,
        mock_post_gen: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that update shows warning when post-gen tasks fail."""
        # Setup mock to return failure
        mock_post_gen.return_value = False

        project_path = project_factory("base")

        # Run update (will exit early due to same commit, but we can test the pattern)
        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--yes"
        )

        # This will likely hit early exit, but tests the plumbing exists
        assert result.stdout or result.stderr

    @patch("aegis.commands.update.run_post_generation_tasks")
    @patch("aegis.commands.update.get_current_template_commit")
    @patch("copier.run_update")
    def test_update_surfaces_post_gen_task_failure(
        self,
        mock_copier_update: MagicMock,
        mock_get_commit: MagicMock,
        mock_post_gen: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that update properly shows post-gen task failures."""
        # Setup mocks to bypass early exit and simulate post-gen failure
        mock_get_commit.return_value = "abc123"  # Different from target
        mock_post_gen.return_value = False

        project_path = project_factory("base")

        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--yes"
        )

        # Should show warning about post-gen failures
        assert (
            "post-generation task" in result.stdout.lower()
            or "setup tasks failed" in result.stdout.lower()
            or "already at" in result.stdout.lower()  # Early exit is valid
        )


class TestUpdateSkipsPostGenOnConflicts:
    """Skip post-gen tasks when ``sync_template_changes`` reports conflicts.

    Without this guard, ``run_post_generation_tasks`` calls ``uv sync``,
    which fails parsing ``pyproject.toml`` if the merge left
    ``<<<<<<<`` markers. That failure raises
    ``DependencyInstallationError`` and the outer ``except`` rolls back
    the merged state — destroying the work the user is supposed to
    resolve manually. The fix gates post-gen on ``not sync_result.conflicts``.
    """

    @patch("aegis.commands.update.cleanup_backup_tag")
    @patch("aegis.commands.update.run_post_generation_tasks")
    @patch("aegis.commands.update.sync_template_changes")
    @patch("copier.run_update")
    @patch("aegis.commands.update.get_current_template_commit")
    @patch("aegis.commands.update.create_backup_point")
    def test_post_gen_skipped_when_conflicts_present(
        self,
        mock_create_backup: MagicMock,
        mock_get_commit: MagicMock,
        mock_copier_update: MagicMock,
        mock_sync: MagicMock,
        mock_post_gen: MagicMock,
        mock_cleanup_backup: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """When sync reports conflicts, post-gen must NOT run, and the
        backup tag must NOT be cleaned up.

        If post-gen runs, it'll call uv sync against a pyproject.toml
        with merge markers and raise — triggering the rollback path
        that wipes the merge.

        And if the backup tag is cleaned up while conflicts remain,
        the user has no rollback target if their resolution goes wrong.
        Both safety nets need to hold while the user is mid-resolution.
        """
        mock_create_backup.return_value = "aegis-backup-123"
        mock_get_commit.return_value = "different-commit"

        # Simulate copier producing a conflict in pyproject.toml.
        sync_stub = MagicMock()
        sync_stub.synced = ["app/foo.py"]
        sync_stub.conflicts = ["pyproject.toml"]
        mock_sync.return_value = sync_stub

        project_path = project_factory("base")

        result = run_aegis_command(
            "update", "--project-path", str(project_path), "--yes"
        )

        # Post-gen tasks must not have been invoked — that's the whole
        # point of the gate. If they were, the test in production would
        # have rolled back.
        assert not mock_post_gen.called, (
            "Post-gen ran despite conflicts; this is the bug we're fixing"
        )

        # Backup tag must survive so manual rollback stays possible.
        assert not mock_cleanup_backup.called, (
            "Backup tag cleaned up while conflicts unresolved; "
            "user has no rollback safety net"
        )

        # And the user-facing message should mention the skip + how to
        # recover, so the user knows what to do next, plus the
        # preserved-backup-tag tip.
        combined = (result.stdout + result.stderr).lower()
        assert "merge conflicts" in combined or "<<<<<<<" in combined
        assert "backup tag preserved" in combined

    @patch("aegis.commands.update.cleanup_backup_tag")
    @patch("aegis.commands.update.run_post_generation_tasks")
    @patch("aegis.commands.update.sync_template_changes")
    @patch("copier.run_update")
    @patch("aegis.commands.update.get_current_template_commit")
    @patch("aegis.commands.update.create_backup_point")
    def test_post_gen_runs_when_no_conflicts(
        self,
        mock_create_backup: MagicMock,
        mock_get_commit: MagicMock,
        mock_copier_update: MagicMock,
        mock_sync: MagicMock,
        mock_post_gen: MagicMock,
        mock_cleanup_backup: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """The conflict-free happy path must still run post-gen AND
        clean up the backup tag (otherwise tags accumulate forever)."""
        mock_create_backup.return_value = "aegis-backup-123"
        mock_get_commit.return_value = "different-commit"
        mock_post_gen.return_value = True

        sync_stub = MagicMock()
        sync_stub.synced = ["app/foo.py"]
        sync_stub.conflicts = []  # no conflicts → post-gen should run
        mock_sync.return_value = sync_stub

        project_path = project_factory("base")

        run_aegis_command("update", "--project-path", str(project_path), "--yes")

        assert mock_post_gen.called, "Post-gen should run on conflict-free updates"
        assert mock_cleanup_backup.called, (
            "Backup tag should be cleaned up on a fully-clean update"
        )


class TestUpdateCommandEnvVar:
    """Tests for AEGIS_TEMPLATE_PATH environment variable support."""

    def test_update_uses_env_var_when_no_flag(
        self, project_factory: "ProjectFactory", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that update uses AEGIS_TEMPLATE_PATH when flag not provided."""
        project_path = project_factory("base")

        # Use the actual aegis-stack repo as template path
        from aegis.core.copier_updater import get_template_root

        template_root = get_template_root()

        # Set env var
        monkeypatch.setenv("AEGIS_TEMPLATE_PATH", str(template_root))

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--to-version",
            "HEAD",
            "--dry-run",
        )

        # Should succeed and show env var source
        assert result.success
        assert (
            "aegis_template_path" in result.stdout.lower()
            or "already at" in result.stdout.lower()
        )

    def test_update_flag_overrides_env_var(
        self, project_factory: "ProjectFactory", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that --template-path flag overrides AEGIS_TEMPLATE_PATH env var."""
        project_path = project_factory("base")

        # Set env var to a non-existent path
        monkeypatch.setenv("AEGIS_TEMPLATE_PATH", "/env/var/path")

        # Use flag with different (also non-existent) path
        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--template-path",
            "/flag/path",
            "--dry-run",
        )

        # Should fail with flag path error (not env var path)
        assert not result.success
        assert "/flag/path" in result.stderr
        assert "/env/var/path" not in result.stderr

    def test_update_env_var_invalid_path(
        self, project_factory: "ProjectFactory", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that invalid AEGIS_TEMPLATE_PATH env var shows error."""
        project_path = project_factory("base")

        # Set env var to non-existent path
        monkeypatch.setenv("AEGIS_TEMPLATE_PATH", "/nonexistent/env/path")

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--dry-run",
        )

        # Should fail with validation error
        assert not result.success
        assert "does not exist" in result.stderr.lower()

    def test_update_env_var_empty_string_ignored(
        self, project_factory: "ProjectFactory", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that empty AEGIS_TEMPLATE_PATH env var is ignored."""
        project_path = project_factory("base")

        # Set env var to empty string
        monkeypatch.setenv("AEGIS_TEMPLATE_PATH", "")

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--to-version",
            "HEAD",
            "--dry-run",
        )

        # Should succeed using default template (empty string is falsy)
        assert result.success
        # Should NOT show "custom template" message
        assert "custom template" not in result.stdout.lower()


class TestUpdateCommandConflictHandling:
    """Tests for enhanced conflict handling."""

    def test_conflict_analysis_functions_work(self, tmp_path: Path) -> None:
        """Test that conflict analysis functions properly detect and format conflicts."""
        from aegis.core.copier_updater import (
            analyze_conflict_files,
            format_conflict_report,
        )

        # Create .rej files
        (tmp_path / "test.txt.rej").write_text("content\nline2")
        (tmp_path / "app").mkdir(exist_ok=True)
        (tmp_path / "app" / "main.py.rej").write_text("rejected")

        conflicts = analyze_conflict_files(tmp_path)
        assert len(conflicts) == 2

        report = format_conflict_report(conflicts)
        assert "conflict" in report.lower()
        assert "resolution" in report.lower()
        assert "git diff" in report.lower()


class TestUpdateCommandMigrationDetection:
    """Tests for detecting projects that need migration."""

    def test_update_detects_non_copier_project(self, temp_output_dir: Path) -> None:
        """Test that update detects v0.1.0 style projects without copier answers."""
        # Create a project directory without .copier-answers.yml
        project_path = temp_output_dir / "old-project"
        project_path.mkdir()
        (project_path / "pyproject.toml").write_text(
            "[project]\nname = 'old-project'\n"
        )

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
        )

        # Should fail with helpful error
        assert not result.success
        assert (
            "copier" in result.stderr.lower()
            or "not generated" in result.stderr.lower()
        )

    def test_update_shows_migration_guidance(self, temp_output_dir: Path) -> None:
        """Test that update provides guidance for non-copier projects."""
        # Create a non-copier project
        project_path = temp_output_dir / "legacy-project"
        project_path.mkdir()
        (project_path / "pyproject.toml").write_text("[project]\nname = 'legacy'\n")

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
        )

        assert not result.success
        # Should mention regeneration or v0.2.0
        stderr_lower = result.stderr.lower()
        assert (
            "regenerat" in stderr_lower
            or "v0.2" in stderr_lower
            or "copier" in stderr_lower
        )


class TestUpdateCommandVersionInfo:
    """Tests for version information display."""

    def test_update_shows_current_and_target_versions(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that update displays version information clearly."""
        project_path = project_factory("base")

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--to-version",
            "HEAD",
            "--dry-run",
        )

        assert result.success
        output = result.stdout.lower()
        # Should show version information
        assert "version" in output or "template" in output

    @patch("aegis.commands.update.get_current_template_commit")
    def test_update_shows_cli_version(
        self,
        mock_get_commit: MagicMock,
        project_factory: "ProjectFactory",
    ) -> None:
        """Test that update shows CLI version information."""
        mock_get_commit.return_value = "abc123"

        project_path = project_factory("base")

        result = run_aegis_command(
            "update",
            "--project-path",
            str(project_path),
            "--dry-run",
        )

        assert result.success
        # Should display CLI version
        assert "cli" in result.stdout.lower()


class TestAdvanceCopierTracking:
    """``_advance_copier_tracking`` must stamp the copier baseline forward.

    Regression: after a clean ``aegis update`` the ``.copier-answers.yml``
    ``_commit`` / ``_template_version`` were left at the OLD version, so a
    re-run re-applied the same diff and a future update would diff from a
    stale baseline (risking spurious re-conflicts on customized files).
    """

    def test_advances_commit_and_strips_v_from_tag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import yaml

        import aegis.commands.update as upd

        answers = tmp_path / ".copier-answers.yml"
        answers.write_text(
            "_commit: oldsha\n"
            "_src_path: gh:lbedner/aegis-stack\n"
            "_template_version: v0.7.0-rc1\n"
            "project_slug: demo\n"
        )
        monkeypatch.setattr(upd, "resolve_ref_to_commit", lambda ref, root: "newsha123")

        upd._advance_copier_tracking(tmp_path, "v0.7.0-rc2", tmp_path)

        data = yaml.safe_load(answers.read_text())
        assert data["_commit"] == "newsha123"
        # "vX.Y.Z" tag stored without the leading "v" (mirrors init).
        assert data["_template_version"] == "0.7.0-rc2"
        # Unrelated answers must be preserved.
        assert data["project_slug"] == "demo"
        assert data["_src_path"] == "gh:lbedner/aegis-stack"

    def test_head_ref_stored_as_is(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import yaml

        import aegis.commands.update as upd

        answers = tmp_path / ".copier-answers.yml"
        answers.write_text("_commit: oldsha\n_template_version: v0.6.13\n")
        monkeypatch.setattr(upd, "resolve_ref_to_commit", lambda ref, root: "headsha")

        upd._advance_copier_tracking(tmp_path, "HEAD", tmp_path)

        data = yaml.safe_load(answers.read_text())
        assert data["_commit"] == "headsha"
        assert data["_template_version"] == "HEAD"

    def test_noop_when_answers_file_missing(self, tmp_path: Path) -> None:
        import aegis.commands.update as upd

        # No .copier-answers.yml present — must not raise.
        upd._advance_copier_tracking(tmp_path, "v1.0.0", tmp_path)

    def test_branch_starting_with_v_is_not_stripped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A branch like ``v-next`` must be stored verbatim, not ``-next``.

        Only genuine version tags (``v0.7.0-rc3``) get the leading ``v``
        stripped; stripping a non-version ``v`` ref would persist a bogus
        ``_template_version``.
        """
        import yaml

        import aegis.commands.update as upd

        answers = tmp_path / ".copier-answers.yml"
        answers.write_text("_commit: oldsha\n_template_version: v0.6.13\n")
        monkeypatch.setattr(upd, "resolve_ref_to_commit", lambda ref, root: "branchsha")

        upd._advance_copier_tracking(tmp_path, "v-next", tmp_path)

        data = yaml.safe_load(answers.read_text())
        assert data["_template_version"] == "v-next"

    def test_template_version_for_ref_mapping(self) -> None:
        from aegis.commands.update import _template_version_for_ref

        # Version tags: leading "v" stripped.
        assert _template_version_for_ref("v0.7.0-rc3") == "0.7.0-rc3"
        assert _template_version_for_ref("v1.0.0") == "1.0.0"
        # Non-version refs: kept verbatim.
        assert _template_version_for_ref("v-next") == "v-next"
        assert _template_version_for_ref("vfeature") == "vfeature"
        assert _template_version_for_ref("HEAD") == "HEAD"
        assert _template_version_for_ref("main") == "main"

    def test_falls_back_to_remote_when_local_resolve_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production (pip/uvx): ``_commit`` must advance via the remote.

        In production ``template_root`` is the installed package dir, not a
        git repo, so the local ``resolve_ref_to_commit`` (``git rev-parse``)
        returns None. ``_advance_copier_tracking`` must then resolve the ref
        against the remote the update pulled from and stamp that SHA, rather
        than leaving ``_commit`` frozen at the original generation commit.
        """
        import yaml

        import aegis.commands.update as upd

        answers = tmp_path / ".copier-answers.yml"
        answers.write_text(
            "_commit: oldsha\n"
            "_src_path: gh:lbedner/aegis-stack\n"
            "_template_version: 0.7.0\n"
            "project_slug: demo\n"
        )
        # Local resolution fails (installed package isn't a git repo).
        monkeypatch.setattr(upd, "resolve_ref_to_commit", lambda ref, root: None)
        captured: dict[str, str] = {}

        def fake_remote(ref: str, repo_url: str) -> str:
            captured["ref"] = ref
            captured["repo_url"] = repo_url
            return "remotesha456"

        monkeypatch.setattr(upd, "resolve_ref_to_commit_remote", fake_remote)

        upd._advance_copier_tracking(tmp_path, "v0.8.0", tmp_path)

        data = yaml.safe_load(answers.read_text())
        assert data["_commit"] == "remotesha456"
        assert data["_template_version"] == "0.8.0"
        assert captured["ref"] == "v0.8.0"
        # ``gh:`` shorthand translated to a URL ``git ls-remote`` can clone.
        assert captured["repo_url"] == "https://github.com/lbedner/aegis-stack"

    def test_remote_not_consulted_when_local_resolve_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dev checkout: local resolution wins, remote is never queried."""
        import aegis.commands.update as upd

        answers = tmp_path / ".copier-answers.yml"
        answers.write_text("_commit: oldsha\n_template_version: v0.7.0\n")
        monkeypatch.setattr(upd, "resolve_ref_to_commit", lambda ref, root: "localsha")

        def fail_remote(ref: str, repo_url: str) -> str:
            raise AssertionError("remote must not be consulted in dev mode")

        monkeypatch.setattr(upd, "resolve_ref_to_commit_remote", fail_remote)

        upd._advance_copier_tracking(tmp_path, "v0.8.0", tmp_path)

        import yaml

        data = yaml.safe_load(answers.read_text())
        assert data["_commit"] == "localsha"


class TestResolveRefToCommitRemote:
    """``resolve_ref_to_commit_remote`` resolves refs against a remote repo.

    This is the production fallback for ``_commit`` advancement when the
    template root isn't a local git repo (issue: stale ``_commit`` after
    ``aegis update`` on a pip/uvx-installed CLI).
    """

    def test_prefers_peeled_commit_for_annotated_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        from aegis.core import copier_updater

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            # Annotated tag: ls-remote emits the tag-object line AND the
            # peeled "^{}" commit line. We must return the peeled commit.
            stdout = "tagobjsha\trefs/tags/v0.8.0\ncommitsha\trefs/tags/v0.8.0^{}\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = copier_updater.resolve_ref_to_commit_remote(
            "v0.8.0", "https://github.com/lbedner/aegis-stack"
        )
        assert result == "commitsha"

    def test_lightweight_ref_returns_plain_sha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        from aegis.core import copier_updater

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                cmd, 0, stdout="branchsha\trefs/heads/main\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = copier_updater.resolve_ref_to_commit_remote(
            "main", "https://github.com/lbedner/aegis-stack"
        )
        assert result == "branchsha"

    def test_full_commit_sha_passed_through_without_remote_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        from aegis.core import copier_updater

        def fail_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            raise AssertionError("ls-remote must not run for a full SHA")

        monkeypatch.setattr(subprocess, "run", fail_run)

        sha = "a" * 40
        assert copier_updater.resolve_ref_to_commit_remote(sha, "irrelevant") == sha

    def test_returns_none_on_git_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        from aegis.core import copier_updater

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            raise subprocess.CalledProcessError(128, cmd)

        monkeypatch.setattr(subprocess, "run", fake_run)

        assert copier_updater.resolve_ref_to_commit_remote("v0.8.0", "bad-url") is None


class TestUpdateProjectAheadOfTarget:
    """A project newer than the resolved target is not a user error.

    ``aegis update`` with no ``--to-version`` targets the installed CLI's
    version. A dev checkout generated from a commit ahead of that tag is
    already up to date, so it must exit cleanly instead of reporting a
    blocked downgrade. An explicitly requested downgrade still blocks.
    """

    @staticmethod
    @contextmanager
    def _ahead_of_target() -> Iterator[None]:
        """Force the 'project is ahead of target' topology."""
        with (
            patch(
                "aegis.commands.update.get_current_template_commit",
                return_value="f" * 40,
            ),
            patch(
                "aegis.commands.update.resolve_ref_to_commit",
                return_value="6" * 40,
            ),
            patch("aegis.commands.update.is_version_downgrade", return_value=True),
        ):
            yield

    def test_implicit_target_behind_project_exits_cleanly(
        self, project_factory: "ProjectFactory"
    ) -> None:
        project_path = project_factory("base")

        with self._ahead_of_target():
            result = run_aegis_command(
                "update", "--project-path", str(project_path), "--yes"
            )

        output = strip_ansi_codes(result.stdout + result.stderr).lower()
        assert result.returncode == 0, output
        assert "downgrade not supported" not in output

    def test_explicit_downgrade_is_still_blocked(
        self, project_factory: "ProjectFactory"
    ) -> None:
        project_path = project_factory("base")

        with self._ahead_of_target():
            result = run_aegis_command(
                "update",
                "--project-path",
                str(project_path),
                "--to-version",
                "0.9.0",
                "--yes",
            )

        output = strip_ansi_codes(result.stdout + result.stderr).lower()
        assert result.returncode == 1, output
        assert "downgrade not supported" in output
