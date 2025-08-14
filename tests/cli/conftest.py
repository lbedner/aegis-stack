"""
Pytest configuration for CLI integration tests.
"""

import pytest


@pytest.fixture(scope="session")
def cli_test_timeout() -> int:
    """Default timeout for CLI commands."""
    return 60  # seconds
