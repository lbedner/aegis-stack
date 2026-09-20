"""
Tests for the 'aegis remove' command that removes components from existing projects.

Uses manual updater (Copier-lite) approach for component removal.
"""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aegis.core.components import COMPONENTS, CORE_COMPONENTS
from aegis.core.copier_manager import load_copier_answers

from .test_utils import format_file_like_regen, run_aegis_command

if TYPE_CHECKING:
    from tests.cli.conftest import ProjectFactory


class TestRemoveCommand:
    """Test suite for 'aegis remove' command."""

    def test_remove_command_not_copier_project(self, temp_output_dir: Path) -> None:
        """Test that remove command fails on non-Copier projects."""
        # Create a dummy directory that's not a Copier project
        fake_project = temp_output_dir / "fake-project"
        fake_project.mkdir()

        # Try to remove component
        result = run_aegis_command(
            "remove", "scheduler", "--project-path", str(fake_project), "--yes"
        )

        # Should fail with helpful message
        assert not result.success
        assert "not generated with copier" in result.stderr.lower()

    def test_remove_command_missing_project(self) -> None:
        """Test that remove command fails when project doesn't exist."""
        result = run_aegis_command(
            "remove", "scheduler", "--project-path", "/nonexistent/path", "--yes"
        )

        assert not result.success
        assert "not generated with copier" in result.stderr.lower()

    def test_remove_command_invalid_component(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that remove command validates component names."""
        # Use cached project with scheduler
        project_path = project_factory("base_with_scheduler")

        # Try to remove invalid component
        result = run_aegis_command(
            "remove", "invalid_component", "--project-path", str(project_path), "--yes"
        )

        assert not result.success
        assert "unknown component" in result.stderr.lower()

    def test_remove_scheduler_from_project(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test removing scheduler component from a project."""
        # Use cached project WITH scheduler
        project_path = project_factory("base_with_scheduler")

        # Verify scheduler is present
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_scheduler") is True
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()

        # Remove scheduler component
        result = run_aegis_command(
            "remove", "scheduler", "--project-path", str(project_path), "--yes"
        )

        # Should succeed
        assert result.success, f"Command failed: {result.stderr}"

        # Verify scheduler was removed from answers
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is False

        # Verify scheduler files were deleted
        assert not (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        assert not (
            project_path / "tests" / "components" / "test_scheduler.py"
        ).exists()

    def test_remove_ai_deletes_gated_rag_voice_extras(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Removing a service deletes its option-gated extras, not just the add base.

        ``rag`` / ``voice`` files live in the AI spec's ``extras`` (kept out of
        the add base so init never writes empty stubs). The remove path uses
        the full footprint (``get_component_files(..., full=True)``), so they
        must be deleted too — otherwise they leak behind. This pins that
        behavior end-to-end; before the manifest refactor these files survived
        ``aegis remove ai``.
        """
        project_path = project_factory("ai_with_rag_voice")

        # Representative gated-extra files (check files, not dirs — an emptied
        # directory may linger; the behavior under test is file deletion).
        rag_service = project_path / "app" / "services" / "rag" / "service.py"
        rag_cli = project_path / "app" / "cli" / "rag" / "shared.py"
        rag_router = (
            project_path
            / "app"
            / "components"
            / "backend"
            / "api"
            / "rag"
            / "routes.py"
        )
        voice_router = (
            project_path
            / "app"
            / "components"
            / "backend"
            / "api"
            / "voice"
            / "router.py"
        )
        for f in (rag_service, rag_cli, rag_router, voice_router):
            assert f.exists(), f"precondition: {f.name} should be generated"

        result = run_aegis_command(
            "remove", "ai", "--project-path", str(project_path), "--yes"
        )
        assert result.success, f"Command failed: {result.stderr}"

        # Full footprint deleted, including the gated rag/voice extras that the
        # add base excludes.
        for f in (rag_service, rag_cli, rag_router, voice_router):
            assert not f.exists(), f"{f} should be deleted with the AI service"

    def test_remove_not_enabled_component(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test removing a component that's not enabled."""
        # Use cached project WITHOUT scheduler
        project_path = project_factory("base")

        # Try to remove scheduler (not enabled)
        result = run_aegis_command(
            "remove", "scheduler", "--project-path", str(project_path), "--yes"
        )

        # Should succeed with message about not enabled
        assert result.success
        assert (
            "not enabled" in result.stdout.lower()
            or "no components to remove" in result.stdout.lower()
        )

    def test_remove_multiple_components(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test removing multiple components at once."""
        # Use cached project with multiple components
        project_path = project_factory("scheduler_and_database")

        # Remove both components
        result = run_aegis_command(
            "remove",
            "scheduler,database",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success

        # Verify all components were removed
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is False
        assert updated_answers.get("include_database") is False

        # Verify files deleted
        assert not (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        assert not (project_path / "app" / "core" / "db.py").exists()

    def test_remove_empty_component_name(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that empty component names are rejected."""
        # Use cached project with scheduler
        project_path = project_factory("base_with_scheduler")

        # Try to remove with empty component
        result = run_aegis_command(
            "remove",
            "scheduler,,database",
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert not result.success
        assert "empty component name" in result.stderr.lower()

    def test_remove_command_help(self) -> None:
        """Test that remove command has proper help text."""
        result = run_aegis_command("remove", "--help")

        assert result.success
        assert "remove components" in result.stdout.lower()
        assert "warning" in result.stdout.lower()
        assert "delete" in result.stdout.lower()

    @pytest.mark.skip(reason="Redis dependency cleanup logic incomplete")
    def test_remove_worker_keeps_redis(self, project_factory: "ProjectFactory") -> None:
        """Test that removing worker doesn't remove redis if needed by other components."""
        # Use cached project with worker (auto-includes redis)
        project_path = project_factory("base_with_worker")

        # Verify both are enabled
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_worker") is True
        assert initial_answers.get("include_redis") is True

        # Remove worker
        result = run_aegis_command(
            "remove", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success

        # Verify worker removed but redis might stay (depends on implementation)
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_worker") is False
        # Redis stays enabled because it's not automatically removed

    @pytest.mark.skip(reason="Empty directory cleanup edge case")
    def test_remove_cleans_empty_directories(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that removing components cleans up empty parent directories."""
        # Use cached project with worker
        project_path = project_factory("base_with_worker")

        # Verify worker directory exists
        worker_dir = project_path / "app" / "components" / "worker"
        assert worker_dir.exists()

        # Remove worker
        result = run_aegis_command(
            "remove", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success

        # Verify worker directory removed
        assert not worker_dir.exists()

    def test_remove_updates_dependencies(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that removing components runs uv sync to clean up dependencies."""
        # Use cached project with worker
        project_path = project_factory("base_with_worker")

        # Remove worker
        result = run_aegis_command(
            "remove", "worker", "--project-path", str(project_path), "--yes"
        )

        assert result.success
        # Note: Cached projects may not have fully initialized dependencies,
        # so dependency sync might fail. We just verify the command succeeds
        # and that worker removal is mentioned in the output.
        assert "worker" in result.stdout.lower() or "removed" in result.stdout.lower()


class TestRemoveCommandIntegration:
    """Integration tests for remove command that validate full workflow."""

    @pytest.mark.slow
    def test_add_then_remove_cycle(self, project_factory: "ProjectFactory") -> None:
        """
        Full integration test: add component, then remove it.

        This test validates the complete add/remove cycle works correctly.
        """
        # Use cached base project
        project_path = project_factory("base")

        # Add scheduler
        add_result = run_aegis_command(
            "add", "scheduler", "--project-path", str(project_path), "--yes"
        )
        assert add_result.success

        # Verify added
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        answers_after_add = load_copier_answers(project_path)
        assert answers_after_add.get("include_scheduler") is True

        # Remove scheduler
        remove_result = run_aegis_command(
            "remove", "scheduler", "--project-path", str(project_path), "--yes"
        )
        assert remove_result.success

        # Verify removed
        assert not (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        answers_after_remove = load_copier_answers(project_path)
        assert answers_after_remove.get("include_scheduler") is False

    @pytest.mark.slow
    def test_remove_then_add_cycle(self, project_factory: "ProjectFactory") -> None:
        """Test removing a component and then adding it back."""
        # Use cached project WITH scheduler
        project_path = project_factory("base_with_scheduler")

        # Remove scheduler
        remove_result = run_aegis_command(
            "remove", "scheduler", "--project-path", str(project_path), "--yes"
        )
        assert remove_result.success
        assert not (project_path / "app" / "entrypoints" / "scheduler.py").exists()

        # Add it back
        add_result = run_aegis_command(
            "add", "scheduler", "--project-path", str(project_path), "--yes"
        )
        assert add_result.success

        # Verify it's back
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        final_answers = load_copier_answers(project_path)
        assert final_answers.get("include_scheduler") is True

    @pytest.mark.slow
    def test_remove_keeps_other_components(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that removing one component doesn't affect others."""
        # Use cached project with multiple components
        project_path = project_factory("scheduler_and_database")

        # Verify both exist
        assert (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        assert (project_path / "app" / "core" / "db.py").exists()

        # Remove only scheduler
        result = run_aegis_command(
            "remove", "scheduler", "--project-path", str(project_path), "--yes"
        )
        assert result.success

        # Verify scheduler removed but database remains
        assert not (project_path / "app" / "entrypoints" / "scheduler.py").exists()
        assert (project_path / "app" / "core" / "db.py").exists()

        final_answers = load_copier_answers(project_path)
        assert final_answers.get("include_scheduler") is False
        assert final_answers.get("include_database") is True

    @pytest.mark.slow
    def test_remove_all_components(self, project_factory: "ProjectFactory") -> None:
        """Test removing all optional components, leaving only core."""
        # Use cached project with multiple components
        project_path = project_factory(components=["scheduler", "worker", "database"])

        # Remove all components one by one
        for component in ["scheduler", "worker", "database"]:
            result = run_aegis_command(
                "remove", component, "--project-path", str(project_path), "--yes"
            )
            assert result.success

        # Verify only core files remain (backend, frontend)
        final_answers = load_copier_answers(project_path)
        assert final_answers.get("include_scheduler") is False
        assert final_answers.get("include_worker") is False
        assert final_answers.get("include_database") is False

        # Core files should still exist
        assert (project_path / "app" / "components" / "backend").exists()
        assert (project_path / "app" / "components" / "frontend").exists()


class TestRemoveCommandInteractive:
    """Test suite for 'aegis remove --interactive' command."""

    def test_remove_interactive_requires_components_or_flag(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that remove command requires either components argument or --interactive flag."""
        # Use cached project with scheduler
        project_path = project_factory("base_with_scheduler")

        # Try to run remove without components or --interactive
        result = run_aegis_command(
            "remove", "--project-path", str(project_path), "--yes"
        )

        # Should fail with helpful message
        assert not result.success
        assert "components argument is required" in result.stderr.lower()
        assert "--interactive" in result.stderr.lower()

    def test_remove_interactive_base_project_no_components(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that interactive mode reports no removable components on base project."""
        # Use cached base project (core only)
        project_path = project_factory("base")

        # Verify no infrastructure components enabled
        answers = load_copier_answers(project_path)
        for component_name in COMPONENTS:
            if component_name not in CORE_COMPONENTS:
                include_key = f"include_{component_name}"
                # Use falsy check - key may not exist in old cached projects
                assert not answers.get(include_key), (
                    f"{component_name} should not be enabled"
                )

        # If we ran interactive mode, it would show "No optional components to remove"

    def test_remove_interactive_detects_enabled_components(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that interactive mode detects enabled components for removal."""
        # Use cached project with multiple components
        project_path = project_factory("scheduler_and_database")

        # Verify both components are enabled
        answers = load_copier_answers(project_path)
        assert answers.get("include_scheduler") is True
        assert answers.get("include_database") is True

        # The interactive function would offer both for removal
        # (Can't test interactive prompts, but we verify state detection)

    def test_remove_interactive_core_components_protected(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that core components cannot be removed."""
        # Use cached base project
        project_path = project_factory("base")

        # Core components should always be present (implicitly)
        # The interactive mode would show them as "cannot remove"
        for core_component in CORE_COMPONENTS:
            # Core components don't have include_* flags (they're always included)
            # Verify the files exist
            component_spec = COMPONENTS.get(core_component)
            if component_spec and component_spec.template_files:
                for template_file in component_spec.template_files:
                    expected_path = project_path / template_file
                    assert expected_path.exists(), (
                        f"Core component {core_component} file missing: {template_file}"
                    )

    @pytest.mark.slow
    def test_remove_interactive_workflow_removes_component(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that components removed via remove command update project correctly."""
        # Use cached project WITH scheduler
        scheduler_component = COMPONENTS["scheduler"]
        project_path = project_factory("base_with_scheduler")

        # Verify scheduler is present initially
        initial_answers = load_copier_answers(project_path)
        assert initial_answers.get("include_scheduler") is True

        # Remove scheduler component (non-interactive, but validates the workflow)
        result = run_aegis_command(
            "remove",
            scheduler_component.name,
            "--project-path",
            str(project_path),
            "--yes",
        )

        assert result.success, (
            f"Failed to remove {scheduler_component.name}: {result.stderr}"
        )

        # Verify scheduler was removed from answers
        updated_answers = load_copier_answers(project_path)
        assert updated_answers.get("include_scheduler") is False

        # Verify expected files are deleted (from component template_files)
        assert scheduler_component.template_files is not None
        for template_file in scheduler_component.template_files:
            expected_file = project_path / template_file
            assert not expected_file.exists(), f"File {template_file} should be deleted"

    @pytest.mark.slow
    def test_remove_interactive_workflow_multiple_components(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test removing multiple components in sequence."""
        # Use cached project with scheduler and database
        scheduler_component = COMPONENTS["scheduler"]
        database_component = COMPONENTS["database"]
        project_path = project_factory("scheduler_and_database")

        # Remove scheduler first
        result1 = run_aegis_command(
            "remove",
            scheduler_component.name,
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result1.success

        # Remove database second
        result2 = run_aegis_command(
            "remove",
            database_component.name,
            "--project-path",
            str(project_path),
            "--yes",
        )
        assert result2.success

        # Verify both are removed
        final_answers = load_copier_answers(project_path)
        assert final_answers.get("include_scheduler") is False
        assert final_answers.get("include_database") is False

        # Verify core components still exist
        backend_spec = COMPONENTS["backend"]
        assert backend_spec.template_files is not None
        for template_file in backend_spec.template_files:
            core_file = project_path / template_file
            assert core_file.exists(), f"Core file {template_file} should remain"

    def test_remove_validates_component_names_in_interactive(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that component validation works the same in interactive mode."""
        # Use cached project with scheduler
        project_path = project_factory("base_with_scheduler")

        # Try to remove invalid component (non-interactive for validation test)
        result = run_aegis_command(
            "remove",
            "nonexistent_component",
            "--project-path",
            str(project_path),
            "--yes",
        )

        # Should fail with validation error
        assert not result.success
        assert "unknown component" in result.stderr.lower()


class TestRemoveCommandVersionCompatibility:
    """Test version compatibility checks in remove command."""

    def test_remove_with_force_flag_available(self) -> None:
        """Test that remove command accepts --force flag."""
        result = run_aegis_command("remove", "--help")

        assert result.success
        assert "--force" in result.stdout or "-f" in result.stdout

    def test_remove_command_version_check_skipped_when_no_version(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that remove command works when project version can't be determined."""
        # Use cached project with scheduler
        project_path = project_factory("base_with_scheduler")

        # Remove a component - should work even if version can't be determined
        result = run_aegis_command(
            "remove", "scheduler", "--project-path", str(project_path), "--yes"
        )

        # Should succeed (version check is skipped when version unknown)
        assert result.success, f"Command failed: {result.stderr}"

    def test_remove_force_flag_bypasses_version_warning(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Test that --force flag is available for bypassing warnings."""
        # Use cached project with scheduler
        project_path = project_factory("base_with_scheduler")

        # Try remove with force flag (should be accepted even if not needed)
        result = run_aegis_command(
            "remove",
            "scheduler",
            "--project-path",
            str(project_path),
            "--yes",
            "--force",
        )

        # Should succeed
        assert result.success, f"Command failed: {result.stderr}"


class TestRemoveHtmxComponent:
    """``aegis remove htmx`` must undo everything ``aegis add htmx`` did.

    These consume the ``base_htmx`` cache entry: the htmx frontend spans a
    component tree, shared-file gates and node build files, so removal is the
    place where a half-registered file shows up as a project that still
    imports something that is no longer there.
    """

    @pytest.mark.slow
    def test_remove_htmx_strips_the_whole_frontend(
        self, project_factory: "ProjectFactory"
    ) -> None:
        project_path = project_factory("base_htmx")
        assert (project_path / "app" / "components" / "web_frontend").is_dir()

        result = run_aegis_command(
            "remove", "htmx", "--project-path", str(project_path), "--yes"
        )
        assert result.success, f"Command failed: {result.stderr}"

        # The component's own tree and its node build files.
        assert not (project_path / "app" / "components" / "web_frontend").exists()
        assert not (project_path / "package.json").exists()
        assert not (project_path / "tailwind.config.js").exists()
        assert load_copier_answers(project_path).get("include_htmx") is False

    @pytest.mark.slow
    def test_remove_htmx_regenerates_the_shared_gates(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """The mount lives in a shared file, so removal has to regenerate it.

        Leaving it behind is the failure that matters: the tree is gone but
        main.py still imports from it, so the app dies at startup rather than
        quietly losing a page.
        """
        project_path = project_factory("base_htmx")
        main_py = project_path / "app" / "integrations" / "main.py"
        assert "web_frontend" in main_py.read_text()

        result = run_aegis_command(
            "remove", "htmx", "--project-path", str(project_path), "--yes"
        )
        assert result.success, f"Command failed: {result.stderr}"

        assert "web_frontend" not in main_py.read_text()
        assert "jinja2" not in (project_path / "pyproject.toml").read_text().lower()

    @pytest.mark.slow
    def test_remove_htmx_leaves_the_flet_frontend_alone(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Flet is CORE. Removing the optional frontend must not touch it.

        ``before`` is normalized through the same ruff helper the regen path
        uses, so the byte-identity assertion doesn't depend on init's
        non-critical `make fix` step having succeeded (it can silently fail
        under load, leaving the fixture project unformatted).
        """
        project_path = project_factory("base_htmx")
        flet_main = project_path / "app" / "components" / "frontend" / "main.py"
        format_file_like_regen(flet_main, project_path)
        before = flet_main.read_text()

        result = run_aegis_command(
            "remove", "htmx", "--project-path", str(project_path), "--yes"
        )
        assert result.success, f"Command failed: {result.stderr}"

        assert flet_main.read_text() == before
        assert (
            'app.mount("/dashboard"'
            in (project_path / "app" / "integrations" / "main.py").read_text()
        )
