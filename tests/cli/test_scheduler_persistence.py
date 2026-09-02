"""
Test scheduler persistence configuration based on user selection.

These tests verify that the scheduler only uses database persistence
when the user explicitly selects database FOR scheduler persistence,
not just when a database component exists independently.
"""

from typing import Any
from unittest.mock import patch

from aegis.cli.interactive import (
    clear_database_engine_selection,
    interactive_project_selection,
    set_database_engine_selection,
    set_postgres_provider_selection,
)
from aegis.constants import WorkerBackends
from aegis.core.template_generator import TemplateGenerator


class TestSchedulerPersistenceTracking:
    """Test scheduler persistence context tracking in interactive flow."""

    @patch("typer.confirm")
    def test_scheduler_backend_selected(self, mock_confirm: Any) -> None:
        """Test scheduler + persistence sets scheduler_backend="sqlite"."""
        # Pre-set database engine (avoids interactive questionary prompt)
        set_database_engine_selection("sqlite")

        try:
            # Simulate: no redis, no worker, yes scheduler, yes persistence, no ingress, no observability, no auth, no AI
            # Note: database is skipped because scheduler adds it
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                True,  # persistence
                False,  # redis
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            assert "scheduler[sqlite]" in components
            assert any(c.startswith("database") for c in components)
            assert scheduler_backend == "sqlite"
            assert services == []
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_scheduler_without_persistence(self, mock_confirm: Any) -> None:
        """Test scheduler without persistence keeps scheduler_backend="memory"."""
        try:
            # Simulate: no redis, no worker, yes scheduler, no persistence, no database, no ingress, no observability, no auth, no AI
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                False,  # persistence
                False,  # database
                False,  # redis
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            assert "scheduler" in components
            assert "database[sqlite]" not in components
            assert scheduler_backend == "memory"
            assert services == []
        finally:
            clear_database_engine_selection()

    @patch("aegis.cli.interactive.select_database_engine", return_value="sqlite")
    @patch("typer.confirm")
    def test_scheduler_not_selected(self, mock_confirm: Any, mock_engine: Any) -> None:
        """Test no scheduler selection keeps scheduler_backend="memory"."""
        try:
            # Simulate: no redis, no worker, no scheduler, yes database, no ingress, no observability, no auth, no AI
            mock_confirm.side_effect = [
                False,  # worker
                False,  # scheduler
                True,  # database
                False,  # redis
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            assert "scheduler" not in components
            assert "database" in components
            assert scheduler_backend == "memory"
            assert services == []
        finally:
            clear_database_engine_selection()

    @patch("aegis.cli.interactive.select_database_engine", return_value="sqlite")
    @patch("typer.confirm")
    def test_database_selected_independently_of_scheduler(
        self, mock_confirm: Any, mock_engine: Any
    ) -> None:
        """Test database selected independently doesn't affect scheduler persistence."""
        try:
            # Simulate: no redis, no worker, no scheduler, yes database, no ingress, no observability, no auth, no AI
            mock_confirm.side_effect = [
                False,  # worker
                False,  # scheduler
                True,  # database
                False,  # redis
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            assert "scheduler" not in components
            assert "database" in components
            assert scheduler_backend == "memory"
            assert services == []
        finally:
            clear_database_engine_selection()

    @patch("aegis.cli.interactive.select_database_engine", return_value="sqlite")
    @patch("typer.confirm")
    def test_both_scheduler_and_independent_database(
        self, mock_confirm: Any, mock_engine: Any
    ) -> None:
        """Test scheduler without persistence + independent database."""
        try:
            # Simulate: no redis, no worker, yes scheduler, no persistence, yes database, no ingress, no observability, no auth, no AI
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                False,  # persistence
                True,  # database
                False,  # redis
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            assert "scheduler" in components
            assert "database" in components
            assert scheduler_backend == "memory"
            assert services == []
        finally:
            clear_database_engine_selection()

    @patch(
        "aegis.cli.interactive.select_worker_backend", return_value=WorkerBackends.ARQ
    )
    @patch("typer.confirm")
    def test_full_stack_with_scheduler_persistence(
        self, mock_confirm: Any, mock_worker_backend: Any
    ) -> None:
        """Test full stack selection with scheduler persistence."""
        # Pre-set database engine
        set_database_engine_selection("sqlite")

        try:
            # Simulate: yes redis, yes worker, yes scheduler, yes persistence, no ingress, no observability, no auth, no AI
            # Note: database is skipped because scheduler adds it
            mock_confirm.side_effect = [
                True,  # redis
                True,  # worker
                True,  # scheduler
                True,  # persistence
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            assert "redis" in components
            assert "worker" in components
            assert "scheduler[sqlite]" in components
            assert any(c.startswith("database") for c in components)
            assert scheduler_backend == "sqlite"
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_scheduler_with_postgres_persistence(self, mock_confirm: Any) -> None:
        """Test scheduler + persistence with PostgreSQL."""
        # Pre-set database engine to PostgreSQL and its host (the scheduler
        # step now asks container-vs-Neon when it adds the database).
        set_database_engine_selection("postgres")
        set_postgres_provider_selection("container")

        try:
            # Simulate: no redis, no worker, yes scheduler, yes persistence, no ingress, no observability, no auth, no AI
            # Note: database is skipped because scheduler adds it
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                True,  # persistence
                False,  # redis
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            assert "scheduler[postgres]" in components
            assert "database[postgres]" in components
            assert scheduler_backend == "postgres"
            assert services == []
        finally:
            clear_database_engine_selection()


class TestBackupJobInclusionLogic:
    """Test that backup job is included in the right scenarios."""

    def test_backup_job_included_with_scheduler_persistence(self) -> None:
        """Test backup job included when scheduler_backend="sqlite"."""
        components = ["scheduler", "database[sqlite]"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="sqlite"
        )

        context = template_gen.get_template_context()

        # Both conditions should be true for backup job
        assert context["scheduler_with_persistence"] == "yes"
        assert context["include_scheduler"] == "yes"
        assert context["include_database"] == "yes"

    def test_backup_job_included_with_independent_selection(self) -> None:
        """Test backup job included when scheduler + database selected independently."""
        components = ["scheduler", "database[sqlite]"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="memory"
        )

        context = template_gen.get_template_context()

        # Independent selection: scheduler_backend="memory" but both present
        assert context["scheduler_with_persistence"] == "no"
        assert context["include_scheduler"] == "yes"
        assert context["include_database"] == "yes"
        # This combination should now include backup job with our changes

    def test_backup_job_not_included_scheduler_only(self) -> None:
        """Test backup job NOT included when only scheduler selected."""
        components = ["scheduler"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="memory"
        )

        context = template_gen.get_template_context()

        assert context["scheduler_with_persistence"] == "no"
        assert context["include_scheduler"] == "yes"
        assert context["include_database"] == "no"
        # This combination should NOT include backup job

    def test_backup_job_not_included_database_only(self) -> None:
        """Test backup job NOT included when only database selected."""
        components = ["database[sqlite]"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="memory"
        )

        context = template_gen.get_template_context()

        assert context["scheduler_with_persistence"] == "no"
        assert context["include_scheduler"] == "no"
        assert context["include_database"] == "yes"
        # This combination should NOT include backup job


class TestTemplateGeneratorPersistenceContext:
    """Test template generator handling of scheduler persistence context."""

    def test_template_context_with_scheduler_persistence(self) -> None:
        """Test template context when scheduler_backend="sqlite"."""
        components = ["scheduler", "database[sqlite]"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="sqlite"
        )

        context = template_gen.get_template_context()

        assert context["include_scheduler"] == "yes"
        assert context["include_database"] == "yes"
        assert context["scheduler_with_persistence"] == "yes"
        assert context["database_engine"] == "sqlite"

    def test_template_context_without_scheduler_persistence(self) -> None:
        """Test template context when scheduler_backend="memory"."""
        components = ["scheduler"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="memory"
        )

        context = template_gen.get_template_context()

        assert context["include_scheduler"] == "yes"
        assert context["include_database"] == "no"
        assert context["scheduler_with_persistence"] == "no"

    def test_template_context_database_without_scheduler_persistence(self) -> None:
        """Test template context with database but no scheduler persistence."""
        components = ["scheduler", "database[sqlite]"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="memory"
        )

        context = template_gen.get_template_context()

        assert context["include_scheduler"] == "yes"
        assert context["include_database"] == "yes"
        assert context["scheduler_with_persistence"] == "no"  # Key difference
        assert context["database_engine"] == "sqlite"

    def test_template_context_default_persistence_false(self) -> None:
        """Test template context defaults scheduler_backend to False."""
        components = ["scheduler", "database[sqlite]"]
        template_gen = TemplateGenerator("test-project", components)

        context = template_gen.get_template_context()

        assert context["scheduler_with_persistence"] == "no"

    def test_template_context_independent_database_selection(self) -> None:
        """Test template context when database selected independently of scheduler."""
        components = ["database[sqlite]"]
        template_gen = TemplateGenerator(
            "test-project", components, scheduler_backend="memory"
        )

        context = template_gen.get_template_context()

        assert context["include_scheduler"] == "no"
        assert context["include_database"] == "yes"
        assert context["scheduler_with_persistence"] == "no"
        assert context["database_engine"] == "sqlite"


class TestSchedulerPersistenceLogic:
    """Test the business logic of scheduler persistence selection."""

    @patch("typer.confirm")
    def test_scheduler_persistence_flow_messaging(self, mock_confirm: Any) -> None:
        """Test that the right messages are shown during scheduler persistence flow."""
        # Pre-set database engine
        set_database_engine_selection("sqlite")

        try:
            # We can't easily test the echo output, but we can test the logic flow
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                True,  # persistence
                False,  # redis
                # database skipped (added by scheduler)
                False,  # storage
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                False,  # AI service
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            # Verify the logic worked correctly
            assert scheduler_backend == "sqlite"
            assert "scheduler[sqlite]" in components
            assert any("database" in comp for comp in components)
        finally:
            clear_database_engine_selection()

    def test_scheduler_persistence_component_format(self) -> None:
        """Test that scheduler persistence results in correct component format."""
        # Pre-set database engine
        set_database_engine_selection("sqlite")

        try:
            with patch("typer.confirm") as mock_confirm:
                mock_confirm.side_effect = [
                    False,  # redis
                    False,  # worker
                    True,  # scheduler
                    True,  # persistence
                    # database skipped (added by scheduler)
                    False,  # storage
                    False,  # ingress
                    False,  # observability
                    False,  # htmx
                    False,  # auth service
                    False,  # payment
                    False,  # AI service
                    False,  # comms
                    False,  # insights
                    False,  # blog service
                    False,  # finance service
                    False,  # documents service
                ]

                components, scheduler_backend, services, _ = (
                    interactive_project_selection()
                )

                # Should have database with engine info when added by scheduler
                database_components = [
                    c for c in components if c.startswith("database")
                ]
                assert len(database_components) == 1
                assert database_components[0] in ["database", "database[sqlite]"]
        finally:
            clear_database_engine_selection()
