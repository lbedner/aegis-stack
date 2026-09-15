import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Pin SQLAlchemy's sqlite dialect into ``sys.modules`` at worker startup.
# ``create_engine("sqlite://...")`` lazily ``__import__``s the dialect on first
# use; under heavy parallel load (xdist workers + many subprocess-spawning
# tests) that import can transiently fail on resource pressure, which
# SQLAlchemy reports as the misleading
# ``NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:sqlite``.
# Importing it now means the lazy import always resolves from cache (no
# filesystem I/O), so it can never fail mid-run.
import sqlalchemy.dialects.sqlite  # noqa: E402, F401


def pytest_configure(config: Any) -> None:
    """Give git an identity for this run without touching the machine's.

    Project generation and several update tests run ``git commit``, which
    needs a name and an email. This used to write them to ``--global``
    config on every invocation, so anyone running ``make test`` had
    ``~/.gitconfig`` rewritten to "Aegis Test" and started authoring their
    own commits under it (#1065).

    The environment carries the same information to every subprocess and
    is gone when the run ends. ``GIT_CONFIG_GLOBAL`` pointing at a file
    that does not exist also means the developer's real global config
    cannot influence a test, which is the other half of the isolation.
    """
    os.environ.setdefault("GIT_AUTHOR_NAME", "Aegis Test")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "test@aegis-stack.dev")
    os.environ.setdefault("GIT_COMMITTER_NAME", "Aegis Test")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "test@aegis-stack.dev")
    os.environ.setdefault(
        "GIT_CONFIG_GLOBAL", str(Path(tempfile.gettempdir()) / "aegis-tests-gitconfig")
    )


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
