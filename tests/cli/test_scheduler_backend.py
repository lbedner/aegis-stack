"""
Tests for scheduler backend detection and expansion logic.

Tests the new functions added to __main__.py for handling scheduler[backend] syntax.
"""

import pytest

from aegis.cli.utils import detect_scheduler_backend
from aegis.core.selection import SelectionError, check_components


class TestSchedulerBackendDetection:
    """Test scheduler backend detection from component lists."""

    def test_detect_scheduler_sqlite_backend(self) -> None:
        """Test detecting scheduler[sqlite] backend."""
        components = ["scheduler[sqlite]", "redis"]
        backend = detect_scheduler_backend(components)
        assert backend == "sqlite"

    def test_detect_scheduler_postgres_backend(self) -> None:
        """Test detecting scheduler[postgres] backend."""
        components = ["worker", "scheduler[postgres]"]
        backend = detect_scheduler_backend(components)
        assert backend == "postgres"

    def test_detect_memory_backend_no_scheduler(self) -> None:
        """Test detecting memory backend when no scheduler present."""
        components = ["redis", "worker"]
        backend = detect_scheduler_backend(components)
        assert backend == "memory"

    def test_detect_memory_backend_plain_scheduler(self) -> None:
        """Test detecting memory backend with plain scheduler."""
        components = ["scheduler", "redis"]
        backend = detect_scheduler_backend(components)
        assert backend == "memory"

    def test_detect_sqlite_backend_legacy_detection(self) -> None:
        """Test detecting sqlite backend via legacy scheduler+database detection."""
        components = ["scheduler", "database", "redis"]
        backend = detect_scheduler_backend(components)
        assert backend == "sqlite"

    def test_direct_backend_overrides_legacy(self) -> None:
        """Test that direct scheduler[backend] overrides legacy detection."""
        components = ["scheduler[postgres]", "database", "redis"]
        backend = detect_scheduler_backend(components)
        assert backend == "postgres"  # Direct syntax wins over legacy


class TestSchedulerDependencyExpansion:
    """A persistent scheduler brings the database it keeps its jobs in,
    and refuses one of another engine."""

    @pytest.mark.parametrize(
        ("components", "expected"),
        [
            (
                "scheduler[sqlite],redis",
                {"scheduler[sqlite]", "database[sqlite]", "redis"},
            ),
            ("scheduler[postgres]", {"scheduler[postgres]", "database[postgres]"}),
            ("scheduler,redis", {"scheduler", "redis"}),
            # An existing database of the same engine is kept, not doubled.
            ("scheduler[sqlite],database", {"scheduler[sqlite]", "database"}),
            (
                "scheduler[postgres],database[neon]",
                {"scheduler[postgres]", "database[neon]"},
            ),
        ],
    )
    def test_a_scheduler_brings_its_database(
        self, components: str, expected: set[str]
    ) -> None:
        assert set(check_components(components)) == expected

    @pytest.mark.parametrize(
        "components",
        ["scheduler[sqlite],database[postgres]", "scheduler[postgres],database"],
    )
    def test_a_database_of_another_engine_is_refused(self, components: str) -> None:
        with pytest.raises(SelectionError, match="scheduler"):
            check_components(components)
