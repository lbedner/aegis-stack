"""The test run must not touch the machine's git configuration (#1065)."""

import subprocess
from pathlib import Path


def test_pytest_configure_writes_no_global_git_config(tmp_path: Path) -> None:
    """``pytest_configure`` used to write --global user.name/user.email, so
    running the suite re-authored the developer's own commits as "Aegis
    Test". Point git's global config at a file of our own and prove the
    hook leaves it alone."""
    import os

    from tests.conftest import pytest_configure

    global_config = tmp_path / "gitconfig"
    before = dict(os.environ)
    os.environ["GIT_CONFIG_GLOBAL"] = str(global_config)
    try:
        pytest_configure(None)
    finally:
        os.environ.clear()
        os.environ.update(before)

    assert not global_config.exists(), global_config.read_text()


def test_a_commit_still_works_with_the_environment_identity(tmp_path: Path) -> None:
    """The reason the global write existed: git refuses to commit without
    an identity. The environment has to carry it to subprocesses."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    done = subprocess.run(
        ["git", "commit", "-qm", "identity comes from the environment"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert done.returncode == 0, done.stderr
    who = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert who.stdout.strip() == "Aegis Test <test@aegis-stack.dev>"
