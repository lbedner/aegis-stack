"""``aegis init`` commits as itself only where git knows nobody.

It wrote "Aegis Stack <noreply@aegis-stack.dev>" into every generated
project's own git config, so everything its owner committed there after was
authored by the bot, and ``aegis deploy`` recorded the bot as the deployer.
"""

import subprocess
from pathlib import Path

import pytest

from aegis.core.copier_manager import AEGIS_GIT_EMAIL, ensure_commit_identity


def _local(repo: Path, key: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "config", "--local", key],
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The suite's own GIT_AUTHOR_* identity must not stand in for config here.
    for var in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)
    path = tmp_path / "app"
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_your_own_identity_is_left_to_author_your_commits(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Ada\n\temail = ada@example.org\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))

    ensure_commit_identity(repo)

    assert _local(repo, "user.email") == ""


def test_with_no_identity_anywhere_init_can_still_commit(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "missing"))

    ensure_commit_identity(repo)

    assert _local(repo, "user.email") == AEGIS_GIT_EMAIL
