"""
Tests for AI backend detection (detect_ai_backend).
"""

from aegis.cli.utils import detect_ai_backend


class TestDetectAIBackend:
    """Test AI backend detection from service list."""

    def test_detect_memory_explicit(self):
        """Test detecting explicit memory backend."""
        services = ["ai[memory]"]
        backend = detect_ai_backend(services)
        assert backend == "memory"

    def test_detect_sqlite_explicit(self):
        """Test detecting explicit sqlite backend."""
        services = ["ai[sqlite]"]
        backend = detect_ai_backend(services)
        assert backend == "sqlite"

    def test_detect_default_memory(self):
        """Test that plain 'ai' defaults to memory."""
        services = ["ai"]
        backend = detect_ai_backend(services)
        assert backend == "memory"

    def test_detect_no_ai_service(self):
        """Test detection when AI service not present."""
        services = ["auth"]
        backend = detect_ai_backend(services)
        assert backend == "memory"  # Default

    def test_detect_empty_list(self):
        """Test detection with empty service list."""
        services = []
        backend = detect_ai_backend(services)
        assert backend == "memory"  # Default

    def test_detect_ai_among_multiple_services(self):
        """Test detecting AI backend among multiple services."""
        services = ["auth", "ai[sqlite]", "comms"]
        backend = detect_ai_backend(services)
        assert backend == "sqlite"
