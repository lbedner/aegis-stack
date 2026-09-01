"""
Tests for enhanced interactive scheduler component selection.

This module tests the context-aware scheduler persistence and database engine
selection functionality added to the interactive component selection.
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


def _prompt_count() -> int:
    """How many confirms one pass through the flow asks.

    Derived, because adding a component or a service adds a prompt: a
    literal here fails in a scheduler test with a bare number when the
    change was somewhere else entirely.
    """
    from aegis.constants import ComponentNames
    from aegis.core.services import SERVICES

    return len(ComponentNames.INFRASTRUCTURE_ORDER) + len(SERVICES)


class TestInteractiveSchedulerFlow:
    """Test cases for enhanced scheduler interactive flow."""

    @patch("typer.confirm")
    def test_scheduler_with_sqlite_persistence(self, mock_confirm: Any) -> None:
        """Test scheduler selection with SQLite database persistence."""
        # Pre-set database engine (avoids interactive questionary prompt)
        set_database_engine_selection("sqlite")

        try:
            # Mock user responses: redis=no, worker=no, scheduler=yes,
            # persistence=yes, ingress=no, observability=no, no auth service, no AI service
            # Note: database is skipped because scheduler adds it
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                True,  # persistence
                False,  # redis
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth
                False,  # payment
                False,  # AI
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            # Should return scheduler[sqlite] and database with SQLite engine info
            assert "scheduler[sqlite]" in components
            assert "database" in components or "database[sqlite]" in components
            assert scheduler_backend == "sqlite"
            assert services == []  # No services selected

            # One confirm per screen: every component and every service.
            assert mock_confirm.call_count == _prompt_count()
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_scheduler_with_postgres_persistence(self, mock_confirm: Any) -> None:
        """Test scheduler selection with PostgreSQL database persistence."""
        # Pre-set database engine to PostgreSQL and its host (the scheduler
        # step now asks container-vs-Neon when it adds the database).
        set_database_engine_selection("postgres")
        set_postgres_provider_selection("container")

        try:
            # Mock user responses: redis=no, worker=no, scheduler=yes,
            # persistence=yes, ingress=no, observability=no, no auth service, no AI service
            # Note: database is skipped because scheduler adds it
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                True,  # persistence
                False,  # redis
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth
                False,  # payment
                False,  # AI
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            # Should return scheduler[postgres] and database[postgres]
            assert "scheduler[postgres]" in components
            assert "database[postgres]" in components
            assert scheduler_backend == "postgres"
            assert services == []
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_scheduler_without_persistence(self, mock_confirm: Any) -> None:
        """Test scheduler selection without persistence (no database)."""
        # No need to pre-set database engine since persistence=no skips that prompt
        try:
            # Mock user responses: redis=no, worker=no, scheduler=yes,
            # persistence=no, database=no, ingress=no, observability=no, no auth, no AI
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                False,  # no persistence
                False,  # database=no
                False,  # redis
                False,  # ingress=no
                False,  # observability=no
                False,  # htmx
                False,  # no auth
                False,  # payment
                False,  # no AI
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, _, _ = interactive_project_selection()

            # Should only return scheduler, no database
            assert "scheduler" in components
            assert not any(c.startswith("database") for c in components)
            assert scheduler_backend == "memory"
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_scheduler_not_selected(self, mock_confirm: Any) -> None:
        """Test when scheduler is not selected."""
        try:
            # Mock user responses: scheduler=no, database=no, ingress=no, observability=no (other components)
            mock_confirm.side_effect = [
                False,  # worker
                False,  # scheduler
                False,  # database
                False,  # redis
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # no auth
                False,  # payment
                False,  # no AI
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, _, _ = interactive_project_selection()

            # Should return empty list (no infrastructure components)
            assert "scheduler" not in components
            assert not any(c.startswith("database") for c in components)
            assert components == []
            assert scheduler_backend == "memory"
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_scheduler_skips_generic_database_prompt(self, mock_confirm: Any) -> None:
        """Test generic database prompt is skipped when added by scheduler."""
        # Pre-set database engine
        set_database_engine_selection("sqlite")

        try:
            # Mock user responses: redis=no, worker=no, scheduler=yes,
            # persistence=yes, ingress=no, observability=no, no auth, no AI
            # The database prompt should be skipped since scheduler adds it
            mock_confirm.side_effect = [
                False,  # worker
                True,  # scheduler
                True,  # persistence
                False,  # redis
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # no auth
                False,  # payment
                False,  # no AI
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, _, _ = interactive_project_selection()

            # Should have scheduler[sqlite] and database
            assert "scheduler[sqlite]" in components
            assert any(c.startswith("database") for c in components)
            assert scheduler_backend == "sqlite"

            # Should not have been prompted for generic database: the
            # database screen is auto-skipped, so the count still lands
            # at one confirm per screen.
            assert mock_confirm.call_count == _prompt_count()
        finally:
            clear_database_engine_selection()

    @patch(
        "aegis.cli.interactive.select_worker_backend", return_value=WorkerBackends.ARQ
    )
    @patch("typer.confirm")
    def test_redis_worker_then_scheduler_sqlite(
        self, mock_confirm: Any, mock_worker_backend: Any
    ) -> None:
        """Test complex flow: redis + worker, then scheduler with SQLite."""
        # Pre-set database engine
        set_database_engine_selection("sqlite")

        try:
            # Mock responses: worker=yes (adds redis, redis prompt skipped),
            # scheduler=yes, persistence=yes, ingress=no, observability=no
            # Note: database is skipped because scheduler adds it
            mock_confirm.side_effect = [
                True,  # worker=yes (auto-adds redis; redis prompt skipped)
                True,  # scheduler=yes
                True,  # persistence=yes
                False,  # ingress=no
                False,  # observability=no
                False,  # htmx
                False,  # no auth
                False,  # payment
                False,  # no AI
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, _, _ = interactive_project_selection()

            # Should have redis (from worker), worker, scheduler[sqlite], database
            assert "redis" in components
            assert "worker" in components
            assert "scheduler[sqlite]" in components
            assert any(c.startswith("database") for c in components)
            assert len(components) == 4
            assert scheduler_backend == "sqlite"
        finally:
            clear_database_engine_selection()

    @patch("aegis.cli.interactive.select_database_engine", return_value="sqlite")
    @patch("typer.confirm")
    def test_standalone_database_selection_still_works(
        self, mock_confirm: Any, mock_engine: Any
    ) -> None:
        """Test that standalone database selection (without scheduler) still works."""
        try:
            # Mock responses: redis=no, worker=no, scheduler=no, database=yes, ingress=no, observability=no, no auth, no AI
            mock_confirm.side_effect = [
                False,  # worker
                False,  # scheduler
                True,  # database
                False,  # redis
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # no auth
                False,  # payment
                False,  # no AI
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, _, _ = interactive_project_selection()

            # Should have just database (no engine suffix when not from scheduler)
            assert components == ["database"]
            assert "scheduler" not in components
            assert scheduler_backend == "memory"
        finally:
            clear_database_engine_selection()
