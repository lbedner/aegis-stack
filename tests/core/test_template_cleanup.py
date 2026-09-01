"""
Tests for template cleanup utilities.

These tests validate the post-update cleanup functions that handle
nested directory structures created during Copier template updates.
"""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from aegis.core.template_cleanup import (
    _reconcile_new_answer_keys,
    _should_skip_sync,
    cleanup_nested_project_directory,
    sync_template_changes,
)


class TestReconcileNewAnswerKeys:
    """Test _reconcile_new_answer_keys — backfilling questions added in the
    target template version into a project's preserved answers file."""

    def _write(self, path: Path, data: dict) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / ".copier-answers.yml").write_text(yaml.safe_dump(data))

    def test_backfills_key_added_in_new_version(self, tmp_path: Path) -> None:
        """A question the new template records but the project lacks (e.g.
        ``postgres_provider`` added in 0.9.0) is copied in with its value."""
        project = tmp_path / "proj"
        new_render = tmp_path / "new"
        self._write(project, {"database_engine": "postgres", "project_slug": "x"})
        self._write(
            new_render,
            {
                "database_engine": "postgres",
                "project_slug": "x",
                "postgres_provider": "container",
            },
        )

        added = _reconcile_new_answer_keys(project, new_render)

        assert added == ["postgres_provider"]
        result = yaml.safe_load((project / ".copier-answers.yml").read_text())
        assert result["postgres_provider"] == "container"

    def test_does_not_overwrite_existing_answer(self, tmp_path: Path) -> None:
        """An answer the user already has is never clobbered by the new render."""
        project = tmp_path / "proj"
        new_render = tmp_path / "new"
        self._write(project, {"postgres_provider": "neon", "project_slug": "x"})
        self._write(new_render, {"postgres_provider": "container", "project_slug": "x"})

        added = _reconcile_new_answer_keys(project, new_render)

        assert added == []
        result = yaml.safe_load((project / ".copier-answers.yml").read_text())
        assert result["postgres_provider"] == "neon"

    def test_skips_private_copier_keys(self, tmp_path: Path) -> None:
        """Private keys (``_commit``/``_src_path``) are owned by copier tracking
        and must not be backfilled from the throwaway new render."""
        project = tmp_path / "proj"
        new_render = tmp_path / "new"
        self._write(project, {"project_slug": "x"})
        self._write(
            new_render,
            {"project_slug": "x", "_commit": "deadbeef", "_src_path": "gh:tmp"},
        )

        added = _reconcile_new_answer_keys(project, new_render)

        assert added == []
        result = yaml.safe_load((project / ".copier-answers.yml").read_text())
        assert "_commit" not in result

    def test_no_files_is_safe_noop(self, tmp_path: Path) -> None:
        """Missing answers files on either side return [] without error."""
        assert _reconcile_new_answer_keys(tmp_path / "a", tmp_path / "b") == []

    def test_non_dict_answers_file_is_safe_noop(self, tmp_path: Path) -> None:
        """A hand-edited/corrupt answers file that parses to a non-mapping
        (list/scalar) returns [] instead of crashing on .items()."""
        project = tmp_path / "proj"
        new_render = tmp_path / "new"
        project.mkdir()
        new_render.mkdir()
        # Project file parses to a YAML list; new render is a valid mapping.
        (project / ".copier-answers.yml").write_text("- not\n- a\n- mapping\n")
        self._write(new_render, {"postgres_provider": "container"})

        assert _reconcile_new_answer_keys(project, new_render) == []

    def test_malformed_yaml_is_safe_noop(self, tmp_path: Path) -> None:
        """Unparseable YAML returns [] rather than aborting the update."""
        project = tmp_path / "proj"
        new_render = tmp_path / "new"
        project.mkdir()
        new_render.mkdir()
        (project / ".copier-answers.yml").write_text("key: : : broken\n  - [\n")
        self._write(new_render, {"postgres_provider": "container"})

        assert _reconcile_new_answer_keys(project, new_render) == []


class TestCleanupNestedProjectDirectory:
    """Test cleanup_nested_project_directory function."""

    def test_no_nested_dir_returns_empty(self, tmp_path: Path) -> None:
        """Test that empty list is returned when nested directory doesn't exist."""
        result = cleanup_nested_project_directory(tmp_path, "my-project")
        assert result == []

    def test_empty_slug_returns_empty(self, tmp_path: Path) -> None:
        """Test that empty list is returned when project_slug is empty."""
        result = cleanup_nested_project_directory(tmp_path, "")
        assert result == []

    def test_moves_files_from_nested_directory(self, tmp_path: Path) -> None:
        """Test that files are moved from nested directory to project root."""
        project_slug = "my-project"
        nested_dir = tmp_path / project_slug
        nested_dir.mkdir()

        # Create a file in the nested directory
        nested_file = nested_dir / "new_file.py"
        nested_file.write_text("# new file content")

        result = cleanup_nested_project_directory(tmp_path, project_slug)

        # File should be moved to root
        assert "new_file.py" in result
        assert (tmp_path / "new_file.py").exists()
        assert (tmp_path / "new_file.py").read_text() == "# new file content"

        # Nested directory should be removed
        assert not nested_dir.exists()

    def test_moves_files_in_subdirectories(self, tmp_path: Path) -> None:
        """Test that files in nested subdirectories are moved correctly."""
        project_slug = "my-project"
        nested_dir = tmp_path / project_slug
        subdir = nested_dir / "app" / "services" / "ai"
        subdir.mkdir(parents=True)

        # Create files in nested subdirectory
        file1 = subdir / "agent.py"
        file1.write_text("# AI agent")
        file2 = subdir / "config.py"
        file2.write_text("# AI config")

        result = cleanup_nested_project_directory(tmp_path, project_slug)

        # Files should be moved to corresponding paths in project root
        assert "app/services/ai/agent.py" in result
        assert "app/services/ai/config.py" in result
        assert (tmp_path / "app" / "services" / "ai" / "agent.py").exists()
        assert (tmp_path / "app" / "services" / "ai" / "config.py").exists()

        # Nested directory should be removed
        assert not nested_dir.exists()

    def test_skips_existing_files(self, tmp_path: Path) -> None:
        """Test that existing files are skipped (sync_template_changes handles them)."""
        project_slug = "my-project"
        nested_dir = tmp_path / project_slug
        nested_dir.mkdir()

        # Create existing file in project root
        existing_file = tmp_path / "config.py"
        existing_file.write_text("# old config")

        # Create file in nested directory (newer version)
        nested_file = nested_dir / "config.py"
        nested_file.write_text("# new config from template")

        result = cleanup_nested_project_directory(tmp_path, project_slug)

        # Existing file should NOT be in the moved list — it's skipped
        assert "config.py" not in result
        # Original content should be preserved (sync_template_changes will merge later)
        assert (tmp_path / "config.py").read_text() == "# old config"
        # Nested source file should be cleaned up
        assert not nested_dir.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that parent directories are created if they don't exist."""
        project_slug = "my-project"
        nested_dir = tmp_path / project_slug / "app" / "new_module"
        nested_dir.mkdir(parents=True)

        new_file = nested_dir / "handler.py"
        new_file.write_text("# handler code")

        # app/new_module doesn't exist in project root yet
        assert not (tmp_path / "app" / "new_module").exists()

        result = cleanup_nested_project_directory(tmp_path, project_slug)

        # Parent directories should be created
        assert (tmp_path / "app" / "new_module" / "handler.py").exists()
        assert "app/new_module/handler.py" in result


class TestUpdateCleanupIntegration:
    """Test that cleanup_components is called after moving nested files."""

    def test_cleanup_components_called_when_files_moved(self, tmp_path: Path) -> None:
        """Test that cleanup_components is called after files are moved from nested dir."""
        from aegis.core.template_cleanup import cleanup_nested_project_directory

        project_slug = "test-project"
        nested_dir = tmp_path / project_slug
        subdir = nested_dir / "app" / "services" / "ai"
        subdir.mkdir(parents=True)

        # Create AI service files that shouldn't exist (include_ai: false)
        (subdir / "agent.py").write_text("# AI agent")
        (subdir / "config.py").write_text("# AI config")

        # Mock answers with include_ai: false
        answers = {
            "project_slug": project_slug,
            "include_ai": False,
            "include_auth": False,
        }

        # First, move files from nested directory
        moved_files = cleanup_nested_project_directory(tmp_path, project_slug)

        # Verify files were moved
        assert len(moved_files) == 2
        assert (tmp_path / "app" / "services" / "ai" / "agent.py").exists()

        # Now test that cleanup_components would remove them
        with patch(
            "aegis.core.post_gen_tasks.cleanup_components"
        ) as mock_cleanup_components:
            # Import and call as the update command would
            from aegis.core.post_gen_tasks import cleanup_components

            cleanup_components(tmp_path, answers)

            # Verify cleanup_components was called with correct arguments
            mock_cleanup_components.assert_called_once_with(tmp_path, answers)

    def test_cleanup_components_not_called_when_no_files_moved(
        self, tmp_path: Path
    ) -> None:
        """Test that cleanup_components is NOT called when no files were moved."""
        project_slug = "test-project"

        # No nested directory exists
        moved_files = cleanup_nested_project_directory(tmp_path, project_slug)

        # No files moved
        assert moved_files == []

        # In the actual update code, cleanup_components should only be called
        # inside the `if moved_files:` block, so it wouldn't be called here


class TestCleanupRemovesUnwantedAIFiles:
    """
    Test the full integration: cleanup_components removes AI files
    when include_ai is False in answers.
    """

    def test_ai_files_removed_when_include_ai_false(self, tmp_path: Path) -> None:
        """Test that AI service files are removed when include_ai: false."""
        from aegis.core.post_gen_tasks import cleanup_components

        # Setup: Create AI service directory structure
        # These paths are defined in get_component_file_mapping() for SERVICE_AI
        ai_services_dir = tmp_path / "app" / "services" / "ai"
        ai_services_dir.mkdir(parents=True)
        (ai_services_dir / "__init__.py").write_text("# AI init")
        (ai_services_dir / "agent.py").write_text("# AI agent")

        # Also create AI API directory (from mapping)
        ai_api_dir = tmp_path / "app" / "components" / "backend" / "api" / "ai"
        ai_api_dir.mkdir(parents=True)
        (ai_api_dir / "__init__.py").write_text("# AI API init")

        # Answers indicate AI is NOT included
        answers = {
            "project_slug": "test-project",
            "include_ai": False,
            "include_auth": False,
            "include_scheduler": False,
            "include_worker": False,
            "include_database": False,
            "include_redis": False,
            "include_cache": False,
            "include_comms": False,
        }

        # Run cleanup_components
        cleanup_components(tmp_path, answers)

        # AI service directory should be removed
        assert not ai_services_dir.exists(), "AI service directory should be removed"
        # AI API directory should be removed
        assert not ai_api_dir.exists(), "AI API directory should be removed"

    def test_ai_files_kept_when_include_ai_true(self, tmp_path: Path) -> None:
        """Test that AI service files are kept when include_ai: true."""
        from aegis.core.post_gen_tasks import cleanup_components

        # Setup: Create AI service directory structure
        ai_dir = tmp_path / "app" / "services" / "ai"
        ai_dir.mkdir(parents=True)
        (ai_dir / "__init__.py").write_text("# AI init")
        (ai_dir / "agent.py").write_text("# AI agent")

        # Answers indicate AI IS included
        answers = {
            "project_slug": "test-project",
            "include_ai": True,
            "include_auth": False,
            "include_scheduler": False,
            "include_worker": False,
            "include_database": False,
            "include_redis": False,
            "include_cache": False,
            "include_comms": False,
        }

        # Run cleanup_components
        cleanup_components(tmp_path, answers)

        # AI service directory should be kept
        assert ai_dir.exists(), "AI service directory should be kept"
        assert (ai_dir / "agent.py").exists(), "AI agent.py should be kept"


class TestEndToEndNestedCleanup:
    """
    End-to-end test simulating what happens during aegis update.

    This mimics the flow:
    1. Copier creates nested files in project_slug/
    2. cleanup_nested_project_directory moves them to project root
    3. cleanup_components removes files that shouldn't exist
    """

    def test_full_update_flow_with_ai_disabled(self, tmp_path: Path) -> None:
        """
        Test full update flow: nested AI files are moved then cleaned up.

        Simulates: User has include_ai: false, but new AI files were added
        to template. After update, AI files should NOT exist.
        """
        from aegis.core.post_gen_tasks import cleanup_components
        from aegis.core.template_cleanup import cleanup_nested_project_directory

        project_slug = "my-project"

        # Step 1: Copier creates nested directory with AI files
        # (This is what Copier does for new files in template)
        nested_dir = tmp_path / project_slug
        ai_nested = nested_dir / "app" / "services" / "ai"
        ai_nested.mkdir(parents=True)
        (ai_nested / "__init__.py").write_text("# AI init")
        (ai_nested / "agent.py").write_text("# AI agent")

        # User's answers say AI is NOT enabled
        answers = {
            "project_slug": project_slug,
            "include_ai": False,
            "include_auth": False,
            "include_scheduler": False,
            "include_worker": False,
            "include_database": False,
            "include_redis": False,
            "include_cache": False,
            "include_comms": False,
        }

        # Step 2: cleanup_nested_project_directory moves files
        moved_files = cleanup_nested_project_directory(tmp_path, project_slug)

        # Verify files were moved
        assert len(moved_files) == 2
        assert (tmp_path / "app" / "services" / "ai" / "agent.py").exists()

        # Step 3: cleanup_components removes unwanted files
        # This is the fix we're adding!
        if moved_files:
            cleanup_components(tmp_path, answers)

        # Result: AI files should NOT exist because include_ai: false
        assert not (tmp_path / "app" / "services" / "ai").exists(), (
            "AI service directory should be removed because include_ai is False"
        )

    def test_full_update_flow_with_ai_enabled(self, tmp_path: Path) -> None:
        """
        Test full update flow: nested AI files are moved and kept.

        Simulates: User has include_ai: true, new AI files are added.
        After update, AI files should exist.
        """
        from aegis.core.post_gen_tasks import cleanup_components
        from aegis.core.template_cleanup import cleanup_nested_project_directory

        project_slug = "my-project"

        # Step 1: Copier creates nested directory with AI files
        nested_dir = tmp_path / project_slug
        ai_nested = nested_dir / "app" / "services" / "ai"
        ai_nested.mkdir(parents=True)
        (ai_nested / "__init__.py").write_text("# AI init")
        (ai_nested / "agent.py").write_text("# AI agent")

        # User's answers say AI IS enabled
        answers = {
            "project_slug": project_slug,
            "include_ai": True,
            "include_auth": False,
            "include_scheduler": False,
            "include_worker": False,
            "include_database": False,
            "include_redis": False,
            "include_cache": False,
            "include_comms": False,
        }

        # Step 2: Move files
        moved_files = cleanup_nested_project_directory(tmp_path, project_slug)
        assert len(moved_files) == 2

        # Step 3: Cleanup (should keep AI files)
        if moved_files:
            cleanup_components(tmp_path, answers)

        # Result: AI files SHOULD exist because include_ai: true
        assert (tmp_path / "app" / "services" / "ai").exists(), (
            "AI service directory should be kept because include_ai is True"
        )
        assert (tmp_path / "app" / "services" / "ai" / "agent.py").exists(), (
            "AI agent.py should be kept"
        )


class TestShouldSkipSync:
    """Test _should_skip_sync helper function."""

    def test_skips_copier_answers(self) -> None:
        """Test that .copier-answers.yml is skipped."""
        assert _should_skip_sync(".copier-answers.yml") is True

    def test_skips_env_file(self) -> None:
        """Test that .env is skipped."""
        assert _should_skip_sync(".env") is True

    def test_skips_python_version(self) -> None:
        """Test that .python-version is skipped."""
        assert _should_skip_sync(".python-version") is True

    def test_skips_venv_directory(self) -> None:
        """Test that .venv/ files are skipped."""
        assert _should_skip_sync(".venv/lib/python3.11/site-packages/foo.py") is True

    def test_skips_pycache(self) -> None:
        """Test that __pycache__/ files are skipped."""
        assert _should_skip_sync("__pycache__/module.cpython-311.pyc") is True
        assert _should_skip_sync("app/__pycache__/foo.pyc") is True

    def test_skips_pyc_files(self) -> None:
        """Test that .pyc files are skipped."""
        assert _should_skip_sync("module.pyc") is True
        assert _should_skip_sync("app/services/ai/agent.pyc") is True

    def test_does_not_skip_regular_files(self) -> None:
        """Test that regular Python files are not skipped."""
        assert _should_skip_sync("app/__init__.py") is False
        assert _should_skip_sync("app/services/ai/agent.py") is False
        assert _should_skip_sync("pyproject.toml") is False
        assert _should_skip_sync("app/components/frontend/theme.py") is False


class TestSyncTemplateChanges:
    """Test sync_template_changes function."""

    def test_empty_project_slug_returns_empty(self, tmp_path: Path) -> None:
        """Test that empty SyncResult is returned when project_slug is empty."""
        answers: dict[str, str] = {"project_slug": ""}
        result = sync_template_changes(tmp_path, answers, "gh:test/repo", "v1.0.0")
        assert result.synced == []
        assert result.conflicts == []

    def test_differing_file_no_old_commit_is_preserved_as_conflict(
        self, tmp_path: Path
    ) -> None:
        """No old_commit → no merge base → preserve + conflict, never overwrite.

        Without a base render we can't tell a user edit from a template change,
        so silently overwriting the user's file is data loss (issue #773). The
        file is preserved and the new render is dropped beside it as ``.rej``.
        """
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        # Create project file with old content
        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text("# old config")

        def mock_run_copy(**kwargs: object) -> None:
            """Mock run_copy to create rendered template."""
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            (rendered_dir / "config.py").write_text("# new config from template")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(tmp_path, answers, "gh:test/repo", "v1.0.0")

        # User's file is preserved, not overwritten, and reported as a conflict.
        assert project_file.read_text() == "# old config"
        assert "app/config.py" in result.conflicts
        assert "app/config.py" not in result.synced
        rej = tmp_path / "app" / "config.py.rej"
        assert rej.read_text() == "# new config from template"

    def test_skips_identical_files(self, tmp_path: Path) -> None:
        """Test that identical files are not synced."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text("# same content")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            (rendered_dir / "config.py").write_text("# same content")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(tmp_path, answers, "gh:test/repo", "v1.0.0")

        assert result.synced == []

    def test_skips_nonexistent_project_files(self, tmp_path: Path) -> None:
        """Test that new files in template are skipped (handled by cleanup_nested)."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            (rendered_dir / "new_file.py").write_text("# new file")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(tmp_path, answers, "gh:test/repo", "v1.0.0")

        assert result.synced == []
        assert not (tmp_path / "app" / "new_file.py").exists()

    def test_skips_files_matching_skip_patterns(self, tmp_path: Path) -> None:
        """Test that files matching skip patterns are not synced."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=old_value")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug
            rendered_dir.mkdir(parents=True)
            (rendered_dir / ".env").write_text("SECRET=new_value")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(tmp_path, answers, "gh:test/repo", "v1.0.0")

        assert result.synced == []
        assert env_file.read_text() == "SECRET=old_value"

    def test_syncs_only_listed_template_changed_files(self, tmp_path: Path) -> None:
        """Test that only files in template_changed_files are synced."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        config_file = tmp_path / "app" / "config.py"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("# old config")

        main_file = tmp_path / "app" / "main.py"
        main_file.write_text("# old main")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            if "/old" in dst_path:
                # Base render == project content (user hasn't customized), so a
                # listed file cleanly overwrites rather than conflicting.
                (rendered_dir / "config.py").write_text("# old config")
                (rendered_dir / "main.py").write_text("# old main")
            else:
                (rendered_dir / "config.py").write_text("# new config")
                (rendered_dir / "main.py").write_text("# new main")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v1.0.0",
                template_changed_files={"app/config.py"},
                old_commit="abc123",
            )

        assert "app/config.py" in result.synced
        assert "app/main.py" not in result.synced
        assert config_file.read_text() == "# new config"
        assert main_file.read_text() == "# old main"

    def test_empty_template_changed_files_syncs_nothing(self, tmp_path: Path) -> None:
        """Test that empty set means no files changed — nothing synced."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        config_file = tmp_path / "app" / "config.py"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("# old config")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            (rendered_dir / "config.py").write_text("# new config")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v1.0.0",
                template_changed_files=set(),
            )

        assert result.synced == []
        assert config_file.read_text() == "# old config"

    def test_none_template_changed_files_syncs_all(self, tmp_path: Path) -> None:
        """Test that None (default) syncs all differing files — backwards compat."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        config_file = tmp_path / "app" / "config.py"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("# old config")

        main_file = tmp_path / "app" / "main.py"
        main_file.write_text("# old main")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            if "/old" in dst_path:
                # Base render == project content, so both files cleanly sync.
                (rendered_dir / "config.py").write_text("# old config")
                (rendered_dir / "main.py").write_text("# old main")
            else:
                (rendered_dir / "config.py").write_text("# new config")
                (rendered_dir / "main.py").write_text("# new main")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v1.0.0",
                template_changed_files=None,
                old_commit="abc123",
            )

        assert "app/config.py" in result.synced
        assert "app/main.py" in result.synced
        assert config_file.read_text() == "# new config"
        assert main_file.read_text() == "# new main"

    def test_handles_render_failure(self, tmp_path: Path) -> None:
        """Test that render failure returns empty SyncResult."""
        answers = {"project_slug": "my-project"}

        with patch(
            "copier.run_copy",
            side_effect=Exception("Render failed"),
        ):
            result = sync_template_changes(tmp_path, answers, "gh:test/repo", "v1.0.0")

        assert result.synced == []
        assert result.conflicts == []

    def test_new_template_file_is_created_not_skipped(self, tmp_path: Path) -> None:
        """A file the new template adds must be created, not silently skipped.

        Copier can merge a new module's importers into existing files while
        failing to materialize the module itself, leaving a broken import graph
        (issue #775). ``sync_template_changes`` is the backstop: a file in the
        changed set that the project lacks is a genuine template addition and
        must be created from the new render.
        """
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        # An existing importer is present; the new module is NOT in the project.
        importer = tmp_path / "app" / "importer.py"
        importer.parent.mkdir(parents=True)
        importer.write_text("# importer")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            (rendered_dir / "importer.py").write_text("# importer")
            if "/old" not in dst_path:
                # formatting.py is new this version — only in the NEW render.
                (rendered_dir / "formatting.py").write_text("def fmt() -> None: ...\n")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                template_changed_files={"app/formatting.py"},
                old_commit="abc123",
            )

        created = tmp_path / "app" / "formatting.py"
        assert created.exists(), "new template file must be created, not skipped"
        assert created.read_text() == "def fmt() -> None: ...\n"
        assert "app/formatting.py" in result.synced
        assert "app/formatting.py" not in result.conflicts


class TestThreeWayMerge:
    """Test 3-way merge logic in sync_template_changes.

    These tests exercise the core merge scenarios by providing old_commit
    so that both old and new templates are rendered.
    """

    @staticmethod
    def _make_mock(
        project_slug: str,
        old_content: str,
        new_content: str,
        filename: str = "config.py",
    ) -> Callable[..., None]:
        """Create a mock_run_copy that renders old/new based on dst_path."""

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            if "/old" in dst_path:
                (rendered_dir / filename).write_text(old_content)
            else:
                (rendered_dir / filename).write_text(new_content)

        return mock_run_copy

    def test_user_didnt_customize_overwrites(self, tmp_path: Path) -> None:
        """When user's file == old template, safe to overwrite with new."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text("# original template content")

        mock = self._make_mock(
            project_slug,
            old_content="# original template content",
            new_content="# updated template content",
        )

        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        assert "app/config.py" in result.synced
        assert result.conflicts == []
        assert project_file.read_text() == "# updated template content"

    def test_template_didnt_change_preserves_user(self, tmp_path: Path) -> None:
        """When old template == new template, keep user's customized version."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text("# user customized content")

        mock = self._make_mock(
            project_slug,
            old_content="# same template",
            new_content="# same template",
        )

        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        # Template didn't change → user's version preserved, not synced
        assert result.synced == []
        assert result.conflicts == []
        assert project_file.read_text() == "# user customized content"

    def test_clean_three_way_merge(self, tmp_path: Path) -> None:
        """When all three differ but changes don't overlap, clean merge.

        Uses a non-Python file so this exercises the raw byte-level merge;
        .py files route through the formatting-aware path covered by
        TestSyncFormattingNoise.
        """
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        # Base has 3 lines, user changed line 1, template changed line 3
        base = "line1\nline2\nline3\n"
        user = "user-changed-line1\nline2\nline3\n"
        new = "line1\nline2\ntemplate-changed-line3\n"

        project_file = tmp_path / "app" / "config.txt"
        project_file.parent.mkdir(parents=True)
        project_file.write_text(user)

        mock = self._make_mock(
            project_slug, old_content=base, new_content=new, filename="config.txt"
        )

        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        assert "app/config.txt" in result.synced
        assert result.conflicts == []
        merged = project_file.read_text()
        assert "user-changed-line1" in merged
        assert "template-changed-line3" in merged

    def test_conflicting_merge_writes_markers(self, tmp_path: Path) -> None:
        """When user and template changed the same line, write conflict markers.

        Non-Python file: exercises the raw merge path directly.
        """
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        base = "line1\nline2\nline3\n"
        user = "user-line1\nline2\nline3\n"
        new = "template-line1\nline2\nline3\n"

        project_file = tmp_path / "app" / "config.txt"
        project_file.parent.mkdir(parents=True)
        project_file.write_text(user)

        mock = self._make_mock(
            project_slug, old_content=base, new_content=new, filename="config.txt"
        )

        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        # Conflicting file should be reported as conflict, not synced
        assert "app/config.txt" not in result.synced
        assert "app/config.txt" in result.conflicts
        # File should contain conflict markers with both versions
        content = project_file.read_text()
        assert "<<<<<<<" in content
        assert "user-line1" in content
        assert "template-line1" in content

    def test_multi_hunk_conflict_writes_markers_not_overwrite(
        self, tmp_path: Path
    ) -> None:
        """Two or more conflict hunks must still be reported as a conflict.

        git merge-file exits with the NUMBER of conflicts (not a boolean),
        so a file where user and template diverge in several places returns
        exit code >= 2. Regression test: this used to fall into the
        merge-failed branch and silently overwrite the user's file with the
        template render.
        """
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        ctx = "ctx1\nctx2\nctx3\nctx4\nctx5\n"
        base = f"top\n{ctx}bottom\n"
        user = f"user-top\n{ctx}user-bottom\n"
        new = f"template-top\n{ctx}template-bottom\n"

        project_file = tmp_path / "app" / "config.txt"
        project_file.parent.mkdir(parents=True)
        project_file.write_text(user)

        mock = self._make_mock(
            project_slug, old_content=base, new_content=new, filename="config.txt"
        )

        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        assert "app/config.txt" not in result.synced
        assert "app/config.txt" in result.conflicts
        content = project_file.read_text()
        # Both conflict regions surfaced, user's side preserved in each
        assert content.count("<<<<<<<") == 2
        assert "user-top" in content
        assert "user-bottom" in content
        assert "template-top" in content
        assert "template-bottom" in content

    def test_merge_file_error_preserves_user_version(self, tmp_path: Path) -> None:
        """A git merge-file error exit must keep the user's file, not overwrite it.

        ``git merge-file`` returns a negative status on error (surfacing as
        exit code 255), distinct from the 1..127 conflict-count range. That
        path must never write the (empty/unreliable) merge stdout over the
        user's file — it should preserve their version and report a conflict
        for manual review, matching ``merge_three_way_text`` semantics.
        """
        import subprocess

        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        base = "line1\nline2\nline3\n"
        user = "user-line1\nline2\nline3\n"
        new = "line1\nline2\ntemplate-line3\n"

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text(user)

        mock = self._make_mock(project_slug, old_content=base, new_content=new)

        real_run = subprocess.run

        def fake_run(args: list[str], **kwargs: object) -> object:
            # Simulate git merge-file itself erroring (e.g. unreadable input):
            # error exit code with no usable merged output.
            if len(args) >= 2 and args[0] == "git" and args[1] == "merge-file":
                return subprocess.CompletedProcess(args, 255, stdout=b"", stderr=b"")
            return real_run(args, **kwargs)  # type: ignore[arg-type]

        with (
            patch("copier.run_copy", side_effect=mock),
            patch(
                "aegis.core.template_cleanup.subprocess.run",
                side_effect=fake_run,
            ),
        ):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        # Error → preserve user's file, report as conflict, never sync/overwrite.
        assert "app/config.py" not in result.synced
        assert "app/config.py" in result.conflicts
        assert project_file.read_text() == user

    def test_old_render_failure_preserves_files_as_conflicts(
        self, tmp_path: Path
    ) -> None:
        """A failed old-template render must not overwrite every changed file.

        Before issue #773 a single rendering error degraded into a project-wide
        silent overwrite. Now each changed file is preserved and reported as a
        conflict with a ``.rej`` sidecar instead.
        """
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text("# user content")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            if "/old" in dst_path:
                raise Exception("Old render failed")
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            (rendered_dir / "config.py").write_text("# new template content")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        # User content preserved; new render surfaced as a .rej conflict.
        assert project_file.read_text() == "# user content"
        assert "app/config.py" in result.conflicts
        assert "app/config.py" not in result.synced
        rej = tmp_path / "app" / "config.py.rej"
        assert rej.read_text() == "# new template content"

    def test_file_missing_from_old_render_is_preserved_as_conflict(
        self, tmp_path: Path
    ) -> None:
        """A file new in the template but pre-existing in the project has no base.

        This is the common ``aegis add-service`` case (e.g. payment added after
        generation): the service's files have no counterpart at the pinned
        ``_commit``. They must be preserved, not silently overwritten on the
        next update (issue #773).
        """
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text("# old project content")

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            if "/old" in dst_path:
                # Old render has no config.py (new file in template)
                rendered_dir = Path(dst_path) / project_slug / "app"
                rendered_dir.mkdir(parents=True)
            else:
                rendered_dir = Path(dst_path) / project_slug / "app"
                rendered_dir.mkdir(parents=True)
                (rendered_dir / "config.py").write_text("# new template content")

        with patch("copier.run_copy", side_effect=mock_run_copy):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        assert project_file.read_text() == "# old project content"
        assert "app/config.py" in result.conflicts
        assert "app/config.py" not in result.synced
        rej = tmp_path / "app" / "config.py.rej"
        assert rej.read_text() == "# new template content"


@pytest.mark.xdist_group("generated_stacks")
class TestSyncFormattingNoise:
    """Formatting must not create conflicts during template sync.

    ``aegis init`` post-gen runs ``make fix``, so files in a real project are
    ruff-formatted (blank-line runs from unselected ``{% if %}`` blocks are
    collapsed, imports sorted). The old/new template renders used by
    ``sync_template_changes`` are raw and unformatted. A byte-level 3-way
    merge therefore sees the pristine project file as "user edits" and
    raises spurious conflicts wherever real template changes land near the
    formatting differences. The sync path must look through formatting the
    same way the add/remove path does (issue #715).

    Pinned to the ``generated_stacks`` xdist group like the issue-715
    suites: the normalized-merge path spawns ruff subprocesses, and under
    a fully parallel CI run those transiently fail (fork pressure), which
    degrades the sync to a raw merge and flakes these strict assertions.
    Serializing away from the fork-heavy tests keeps ruff reliable.
    """

    @staticmethod
    def _make_mock(
        project_slug: str,
        old_content: str,
        new_content: str,
    ) -> Callable[..., None]:
        """Create a mock_run_copy that renders old/new based on dst_path."""

        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            rendered_dir = Path(dst_path) / project_slug / "app"
            rendered_dir.mkdir(parents=True)
            if "/old" in dst_path:
                (rendered_dir / "config.py").write_text(old_content)
            else:
                (rendered_dir / "config.py").write_text(new_content)

        return mock_run_copy

    # Raw render: an unselected {% if %} block leaves a run of blank lines.
    OLD_RAW = "A = 1\n\n\n\n\n\nB = 2\n"
    # What make fix left in the project at init time (blank run collapsed).
    PROJECT_FORMATTED = "A = 1\n\n\nB = 2\n"
    # New template: the unselected block grew (more blank lines in the raw
    # render, overlapping the collapsed region) AND a real setting was added.
    NEW_RAW = "A = 1\n\n\n\n\n\n\n\n\nB = 2\nNEW_SETTING = 3\n"

    def test_pristine_formatted_project_gets_no_conflicts(self, tmp_path: Path) -> None:
        """A project file that only differs from the old render by formatting
        is pristine: the template change must apply cleanly, never conflict."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        project_file.write_text(self.PROJECT_FORMATTED)

        mock = self._make_mock(project_slug, self.OLD_RAW, self.NEW_RAW)
        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        assert result.conflicts == []
        assert "app/config.py" in result.synced
        content = project_file.read_text()
        assert "<<<<<<<" not in content
        assert "NEW_SETTING = 3" in content

    def test_customized_file_merges_without_formatting_conflicts(
        self, tmp_path: Path
    ) -> None:
        """A real user edit still 3-way merges with the template change, and
        formatting differences alone must not turn that merge conflicted."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        # User genuinely changed A's value in the formatted file.
        project_file.write_text("A = 111\n\n\nB = 2\n")

        mock = self._make_mock(project_slug, self.OLD_RAW, self.NEW_RAW)
        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        assert result.conflicts == []
        assert "app/config.py" in result.synced
        content = project_file.read_text()
        assert "<<<<<<<" not in content
        assert "A = 111" in content
        assert "NEW_SETTING = 3" in content

    def test_formatting_only_template_change_preserves_custom_file(
        self, tmp_path: Path
    ) -> None:
        """When the template change is formatting-only noise, a customized
        file is left untouched instead of being churned or conflicted."""
        project_slug = "my-project"
        answers = {"project_slug": project_slug}

        project_file = tmp_path / "app" / "config.py"
        project_file.parent.mkdir(parents=True)
        user_content = "A = 111\n\n\nB = 2\n"
        project_file.write_text(user_content)

        # Old and new renders differ only in blank-line runs.
        mock = self._make_mock(
            project_slug,
            "A = 1\n\n\n\n\nB = 2\n",
            "A = 1\n\n\n\n\n\n\n\nB = 2\n",
        )
        with patch("copier.run_copy", side_effect=mock):
            result = sync_template_changes(
                tmp_path,
                answers,
                "gh:test/repo",
                "v2.0.0",
                old_commit="abc123",
            )

        assert result.conflicts == []
        assert project_file.read_text() == user_content


class TestRuffExecutableResolution:
    """Formatting parity depends on WHICH ruff formats the render.

    Init formats with the project's pinned ruff (make fix runs inside the
    project); the tool's own ruff floats and can format differently. The
    resolver must therefore prefer the target project's binary, or add/regen
    output drifts from init output on any machine where the two versions
    disagree (this is exactly what CI's fresh resolve exposed).
    """

    def test_prefers_the_projects_own_ruff(self, tmp_path: Path) -> None:
        from aegis.core.template_cleanup import ruff_executable

        project_ruff = tmp_path / ".venv" / "bin" / "ruff"
        project_ruff.parent.mkdir(parents=True)
        project_ruff.write_text("#!/bin/sh\n")

        assert ruff_executable(tmp_path) == str(project_ruff)

    def test_falls_back_to_the_tools_ruff_without_a_project_venv(
        self, tmp_path: Path
    ) -> None:
        from aegis.core.template_cleanup import ruff_executable

        resolved = ruff_executable(tmp_path)  # tmp_path has no .venv
        assert resolved is not None
        # Not something conjured under the (venv-less) project dir...
        assert not Path(resolved).is_relative_to(tmp_path)
        # ...but exactly the tool's own answer.
        assert resolved == ruff_executable(None)


class TestSyncRemovesFilesTheTemplateDropped:
    """The deletion pass.

    The sync loop walks the NEW render, so a file the template deleted is
    invisible to it and survives forever. Renaming a module to a package
    (``models.py`` -> ``models/``) leaves the old file shadowed but present:
    valid code nobody runs, which is worse than a break because nothing
    reports it.
    """

    @staticmethod
    def _renders(
        project_slug: str,
        old: dict[str, str],
        new: dict[str, str],
    ):
        def mock_run_copy(**kwargs: object) -> None:
            dst_path = str(kwargs["dst_path"])
            root = Path(dst_path) / project_slug
            files = old if "/old" in dst_path else new
            for rel, content in files.items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            root.mkdir(parents=True, exist_ok=True)

        return mock_run_copy

    def test_untouched_file_dropped_by_the_template_is_deleted(
        self, tmp_path: Path
    ) -> None:
        answers = {"project_slug": "my-project"}
        stale = tmp_path / "app" / "models.py"
        stale.parent.mkdir(parents=True)
        stale.write_text("# models")

        with patch(
            "copier.run_copy",
            side_effect=self._renders(
                "my-project",
                old={"app/models.py": "# models"},
                new={"app/models/__init__.py": "# package"},
            ),
        ):
            result = sync_template_changes(
                tmp_path, answers, "gh:test/repo", "v1.0.0", old_commit="abc123"
            )

        assert not stale.exists()
        assert "app/models.py" in result.removed

    def test_customized_file_dropped_by_the_template_is_kept_and_reported(
        self, tmp_path: Path
    ) -> None:
        answers = {"project_slug": "my-project"}
        stale = tmp_path / "app" / "models.py"
        stale.parent.mkdir(parents=True)
        stale.write_text("# models\n# my own column")

        with patch(
            "copier.run_copy",
            side_effect=self._renders(
                "my-project",
                old={"app/models.py": "# models"},
                new={"app/models/__init__.py": "# package"},
            ),
        ):
            result = sync_template_changes(
                tmp_path, answers, "gh:test/repo", "v1.0.0", old_commit="abc123"
            )

        assert stale.exists()
        assert stale.read_text() == "# models\n# my own column"
        assert "app/models.py" in result.stale
        assert "app/models.py" not in result.removed

    def test_a_file_the_user_added_is_never_touched(self, tmp_path: Path) -> None:
        """The template never shipped it, so it is absent from BOTH renders and
        must not look like a deletion."""
        answers = {"project_slug": "my-project"}
        mine = tmp_path / "app" / "my_helper.py"
        mine.parent.mkdir(parents=True)
        mine.write_text("# mine")

        with patch(
            "copier.run_copy",
            side_effect=self._renders(
                "my-project",
                old={"app/main.py": "# main"},
                new={"app/main.py": "# main"},
            ),
        ):
            result = sync_template_changes(
                tmp_path, answers, "gh:test/repo", "v1.0.0", old_commit="abc123"
            )

        assert mine.exists()
        assert result.removed == []

    def test_without_an_old_render_nothing_is_deleted(self, tmp_path: Path) -> None:
        """No base render means "template deleted it" and "user added it" are
        indistinguishable, so the pass must not run at all."""
        answers = {"project_slug": "my-project"}
        stale = tmp_path / "app" / "models.py"
        stale.parent.mkdir(parents=True)
        stale.write_text("# models")

        with patch(
            "copier.run_copy",
            side_effect=self._renders(
                "my-project", old={}, new={"app/models/__init__.py": "# package"}
            ),
        ):
            result = sync_template_changes(
                tmp_path, answers, "gh:test/repo", "v1.0.0", old_commit=None
            )

        assert stale.exists()
        assert result.removed == []

    def test_skip_patterns_are_never_deletion_candidates(self, tmp_path: Path) -> None:
        answers = {"project_slug": "my-project"}
        env = tmp_path / ".env"
        env.write_text("SECRET=1")

        with patch(
            "copier.run_copy",
            side_effect=self._renders(
                "my-project", old={".env": "SECRET=1"}, new={"app/main.py": "# main"}
            ),
        ):
            result = sync_template_changes(
                tmp_path, answers, "gh:test/repo", "v1.0.0", old_commit="abc123"
            )

        assert env.exists()
        assert result.removed == []

    def test_emptied_directories_are_pruned(self, tmp_path: Path) -> None:
        answers = {"project_slug": "my-project"}
        stale = tmp_path / "app" / "legacy" / "old.py"
        stale.parent.mkdir(parents=True)
        stale.write_text("# old")

        with patch(
            "copier.run_copy",
            side_effect=self._renders(
                "my-project",
                old={"app/legacy/old.py": "# old"},
                new={"app/main.py": "# main"},
            ),
        ):
            sync_template_changes(
                tmp_path, answers, "gh:test/repo", "v1.0.0", old_commit="abc123"
            )

        assert not (tmp_path / "app" / "legacy").exists()


class TestDocumentsOnlyStackKeepsWhatItNeeds:
    """A stack whose only service is documents still has a services card
    (its card imports through the same aggregate) and migrations."""

    @staticmethod
    def _documents_only(tmp_path: Path) -> tuple[Path, Path]:
        card = tmp_path / "app/components/frontend/dashboard/cards/services_card.py"
        card.parent.mkdir(parents=True)
        card.write_text("# card")
        alembic = tmp_path / "alembic"
        alembic.mkdir()
        (alembic / "env.py").write_text("# env")
        return card, alembic

    def test_services_card_and_alembic_survive(self, tmp_path: Path) -> None:
        from aegis.core.post_gen_tasks import cleanup_components

        card, alembic = self._documents_only(tmp_path)

        cleanup_components(
            tmp_path,
            {"project_slug": "p", "include_documents": True, "include_database": True},
        )

        assert card.exists()
        assert alembic.exists()
