from typing import Any

import pytest


def pytest_addoption(parser: Any) -> None:
    """Add custom pytest options."""
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow tests (CLI integration tests with project generation)",
    )


@pytest.fixture
def skip_slow_tests(request: Any) -> None:
    """Skip tests marked as slow unless --runslow is passed."""
    if request.config.getoption("--runslow"):
        return
    pytest.skip("need --runslow option to run")
