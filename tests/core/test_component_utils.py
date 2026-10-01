"""
Tests for component name parsing utilities.

This module tests all the component utility functions to ensure robust
parsing of component names with engine information.
"""

import pytest

from aegis.core.component_utils import (
    clean_component_names,
    extract_base_component_name,
    extract_engine_info,
    find_components_with_engine,
    format_component_with_engine,
    has_engine_info,
    parse_component_name,
    restore_engine_info,
)


class TestParseComponentName:
    """Test the core component name parsing function."""

    def test_parse_a_list_of_options(self) -> None:
        """A component with two option axes takes both in one bracket
        (``inference[ollama,docker]``); each spec validates its own."""
        assert parse_component_name("inference[ollama,docker]") == (
            "inference",
            "ollama,docker",
        )

    def test_parse_simple_component(self) -> None:
        """Test parsing component without engine info."""
        base, engine = parse_component_name("scheduler")
        assert base == "scheduler"
        assert engine is None

    def test_parse_component_with_engine(self) -> None:
        """Test parsing component with engine info."""
        base, engine = parse_component_name("database[sqlite]")
        assert base == "database"
        assert engine == "sqlite"

    def test_parse_component_with_empty_engine(self) -> None:
        """Test parsing component with empty brackets."""
        base, engine = parse_component_name("database[]")
        assert base == "database"
        assert engine is None

    def test_parse_component_with_complex_names(self) -> None:
        """Test parsing components with hyphens and underscores."""
        base, engine = parse_component_name("my-component_v2[postgres-14]")
        assert base == "my-component_v2"
        assert engine == "postgres-14"

    def test_parse_invalid_empty_string(self) -> None:
        """Test parsing empty string raises error."""
        with pytest.raises(
            ValueError, match="Component name must be a non-empty string"
        ):
            parse_component_name("")

    def test_parse_invalid_whitespace_only(self) -> None:
        """Test parsing whitespace-only string raises error."""
        with pytest.raises(
            ValueError, match="Component name cannot be empty or whitespace"
        ):
            parse_component_name("   ")

    def test_parse_invalid_none(self) -> None:
        """Test parsing None raises error."""
        with pytest.raises(
            ValueError, match="Component name must be a non-empty string"
        ):
            parse_component_name(None)  # type: ignore

    def test_parse_invalid_format(self) -> None:
        """Test parsing invalid format raises error."""
        with pytest.raises(ValueError, match="Invalid component name format"):
            parse_component_name("database[sqlite")  # Missing closing bracket

        with pytest.raises(ValueError, match="Invalid component name format"):
            parse_component_name("database]sqlite[")  # Wrong bracket order

        with pytest.raises(ValueError, match="Invalid component name format"):
            parse_component_name("123invalid")  # Can't start with number

    def test_parse_strips_whitespace(self) -> None:
        """Test parsing strips leading/trailing whitespace."""
        base, engine = parse_component_name("  scheduler  ")
        assert base == "scheduler"
        assert engine is None


class TestExtractBaseComponentName:
    """Test base component name extraction."""

    def test_extract_from_simple_component(self) -> None:
        """Test extraction from component without engine."""
        assert extract_base_component_name("scheduler") == "scheduler"

    def test_extract_from_component_with_engine(self) -> None:
        """Test extraction from component with engine."""
        assert extract_base_component_name("database[sqlite]") == "database"

    def test_extract_from_complex_component(self) -> None:
        """Test extraction from complex component names."""
        assert (
            extract_base_component_name("my-worker_v2[redis-cluster]") == "my-worker_v2"
        )


class TestExtractEngineInfo:
    """Test engine information extraction."""

    def test_extract_from_simple_component(self) -> None:
        """Test extraction from component without engine."""
        assert extract_engine_info("scheduler") is None

    def test_extract_from_component_with_engine(self) -> None:
        """Test extraction from component with engine."""
        assert extract_engine_info("database[sqlite]") == "sqlite"

    def test_extract_from_component_with_empty_engine(self) -> None:
        """Test extraction from component with empty brackets."""
        assert extract_engine_info("database[]") is None


class TestFormatComponentWithEngine:
    """Test component formatting with engine info."""

    def test_format_without_engine(self) -> None:
        """Test formatting component without engine."""
        assert format_component_with_engine("scheduler", None) == "scheduler"

    def test_format_with_engine(self) -> None:
        """Test formatting component with engine."""
        assert format_component_with_engine("database", "sqlite") == "database[sqlite]"

    def test_format_strips_whitespace(self) -> None:
        """Test formatting strips whitespace."""
        assert (
            format_component_with_engine("  scheduler  ", "  redis  ")
            == "scheduler[redis]"
        )

    def test_format_invalid_base_name(self) -> None:
        """Test formatting with invalid base name."""
        with pytest.raises(
            ValueError, match="Base component name must be a non-empty string"
        ):
            format_component_with_engine("", "sqlite")

        with pytest.raises(
            ValueError, match="Base component name must be a non-empty string"
        ):
            format_component_with_engine(None, "sqlite")  # type: ignore

    def test_format_invalid_engine(self) -> None:
        """Test formatting with invalid engine."""
        with pytest.raises(ValueError, match="Engine must be a non-empty string"):
            format_component_with_engine("database", "")


class TestCleanComponentNames:
    """Test cleaning component names list."""

    def test_clean_mixed_components(self) -> None:
        """Test cleaning list with mixed component types."""
        components = ["redis", "database[sqlite]", "scheduler", "worker[async]"]
        expected = ["redis", "database", "scheduler", "worker"]
        assert clean_component_names(components) == expected

    def test_clean_no_engine_components(self) -> None:
        """Test cleaning list with no engine components."""
        components = ["redis", "scheduler", "worker"]
        assert clean_component_names(components) == components

    def test_clean_empty_list(self) -> None:
        """Test cleaning empty list."""
        assert clean_component_names([]) == []


class TestRestoreEngineInfo:
    """Test restoring engine info from original components."""

    def test_restore_simple_case(self) -> None:
        """Test restoring engine info in simple case."""
        resolved = ["redis", "database", "scheduler"]
        original = ["database[sqlite]", "scheduler"]
        expected = ["redis", "database[sqlite]", "scheduler"]
        assert restore_engine_info(resolved, original) == expected

    def test_restore_multiple_engines(self) -> None:
        """Test restoring multiple engine components."""
        resolved = ["database", "worker", "redis"]
        original = ["database[postgres]", "worker[celery]"]
        expected = ["database[postgres]", "worker[celery]", "redis"]
        assert restore_engine_info(resolved, original) == expected

    def test_restore_no_original_engines(self) -> None:
        """Test restoring when no original components have engines."""
        resolved = ["redis", "database", "scheduler"]
        original = ["database", "scheduler"]
        expected = ["redis", "database", "scheduler"]
        assert restore_engine_info(resolved, original) == expected

    def test_restore_empty_lists(self) -> None:
        """Test restoring with empty lists."""
        assert restore_engine_info([], []) == []
        assert restore_engine_info(["redis"], []) == ["redis"]
        assert restore_engine_info([], ["database[sqlite]"]) == []


class TestFindComponentsWithEngine:
    """Test finding components by base name."""

    def test_find_matching_components(self) -> None:
        """Test finding components that match base name."""
        components = ["redis", "database[sqlite]", "database[postgres]", "scheduler"]
        matches = find_components_with_engine(components, "database")
        assert matches == ["database[sqlite]", "database[postgres]"]

    def test_find_no_matches(self) -> None:
        """Test finding components with no matches."""
        components = ["redis", "scheduler", "worker"]
        matches = find_components_with_engine(components, "database")
        assert matches == []

    def test_find_simple_component(self) -> None:
        """Test finding simple component without engine."""
        components = ["redis", "database", "scheduler"]
        matches = find_components_with_engine(components, "redis")
        assert matches == ["redis"]


class TestHasEngineInfo:
    """Test checking if component has engine info."""

    def test_component_with_engine(self) -> None:
        """Test component with engine info."""
        assert has_engine_info("database[sqlite]") is True

    def test_component_without_engine(self) -> None:
        """Test component without engine info."""
        assert has_engine_info("scheduler") is False

    def test_component_with_empty_engine(self) -> None:
        """Test component with empty engine brackets."""
        assert has_engine_info("database[]") is False


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_malformed_component_names(self) -> None:
        """Test handling of malformed component names."""
        malformed_names = [
            "database[sqlite",  # Missing closing bracket
            "database]sqlite[",  # Wrong bracket order
            "database[[sqlite]]",  # Double brackets
            "database[sqlite][postgres]",  # Multiple engines
            "[sqlite]",  # Missing base name
            "123database",  # Invalid start character
        ]

        for name in malformed_names:
            with pytest.raises(ValueError):
                parse_component_name(name)

    def test_unicode_component_names(self) -> None:
        """Test handling of unicode in component names."""
        # Should reject unicode characters
        with pytest.raises(ValueError):
            parse_component_name("databäse[sqlite]")

    def test_very_long_component_names(self) -> None:
        """Test handling of very long component names."""
        long_name = "a" * 100
        long_engine = "b" * 50

        # Should parse successfully
        base, engine = parse_component_name(f"{long_name}[{long_engine}]")
        assert base == long_name
        assert engine == long_engine


class TestSchedulerBackendParsing:
    """Test scheduler[backend] parsing specifically."""

    def test_scheduler_with_sqlite_backend(self) -> None:
        """Test parsing scheduler[sqlite] syntax."""
        base, engine = parse_component_name("scheduler[sqlite]")
        assert base == "scheduler"
        assert engine == "sqlite"

    def test_scheduler_with_postgres_backend(self) -> None:
        """Test parsing scheduler[postgres] syntax."""
        base, engine = parse_component_name("scheduler[postgres]")
        assert base == "scheduler"
        assert engine == "postgres"

    def test_scheduler_memory_backend(self) -> None:
        """Test parsing simple scheduler (memory backend)."""
        base, engine = parse_component_name("scheduler")
        assert base == "scheduler"
        assert engine is None

    def test_extract_scheduler_backends(self) -> None:
        """Test extracting scheduler backends from component lists."""
        components = ["scheduler[sqlite]", "redis", "worker"]

        # Should find scheduler with sqlite backend
        scheduler_components = find_components_with_engine(components, "scheduler")
        assert scheduler_components == ["scheduler[sqlite]"]

        # Should extract backend correctly
        scheduler_backend = extract_engine_info("scheduler[sqlite]")
        assert scheduler_backend == "sqlite"

    def test_clean_scheduler_component_names(self) -> None:
        """Test cleaning scheduler component names removes backends."""
        components = ["scheduler[sqlite]", "database[postgres]", "redis"]
        clean = clean_component_names(components)
        assert clean == ["scheduler", "database", "redis"]

    def test_restore_scheduler_engine_info(self) -> None:
        """Test restoring scheduler backend info."""
        resolved = ["redis", "scheduler", "database"]
        original = ["scheduler[sqlite]", "database[postgres]"]

        restored = restore_engine_info(resolved, original)
        assert "scheduler[sqlite]" in restored
        assert "database[postgres]" in restored
        assert "redis" in restored
