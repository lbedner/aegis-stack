"""Where a run's work is kept, and how it reaches GitHub: the worktree of
its branch under the runner's worktrees folder (``kept``) or a fresh one
for a question (``fresh``), the commits it has not pushed (``unpushed``),
and its branch pushed with a token (``push``) and its pull request opened
(``pull_request``). Every git step has ``GIT_SECONDS`` and nobody to ask."""

import base64
from collections.abc import Iterator
import contextlib
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile

import httpx

# What git is given for one step (a fetch that waits on a prompt or a dead
# network would otherwise hold the runner for good).
GIT_SECONDS = 60.0


# Where a branch is pushed, and the API a pull request is opened through
# (``GITHUB_TRANSPORT`` answers for it in a test).
GITHUB_GIT = "https://github.com/{slug}.git"


class WorktreeRefusedError(ValueError):
    """The branch is no branch name, names a place outside the worktrees
    folder, or its worktree is on something else."""


# A branch's commits no remote branch has.
UNPUSHED = ("HEAD", "--not", "--remotes")


def unpushed(path: Path) -> int | None:
    """How many of the branch's commits no remote branch has, as the
    remotes were last fetched; None where git cannot say, which never
    costs a run its answer."""
    counted = git(path, "rev-list", "--count", *UNPUSHED, check=False)
    return int(counted.stdout.strip()) if counted.returncode == 0 else None


def push(path: Path, slug: str, branch: str, token: str) -> None:
    """``branch`` pushed to GitHub over HTTPS with ``token``, and the
    remote's branch known to be there, so nothing is left to push. The
    repository's hooks, which its agent may have written, are not run with
    the token in git's environment."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }
    where = GITHUB_GIT.format(slug=slug)
    git(
        path,
        "push",
        "--quiet",
        "--no-verify",
        where,
        f"HEAD:refs/heads/{branch}",
        env=env,
    )
    git(path, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")


async def pull_request(
    github: httpx.AsyncClient, slug: str, branch: str, title: str, body: str
) -> str:
    """The link of the pull request opened for ``branch`` on ``slug``'s
    default branch, or of the one open for it already."""
    repo = await github.get(f"/repos/{slug}")
    repo.raise_for_status()
    made = await github.post(
        f"/repos/{slug}/pulls",
        json={
            "title": title,
            "head": branch,
            "base": repo.json()["default_branch"],
            "body": body,
        },
    )
    if made.status_code == 422:  # one is open for it already
        owner = slug.split("/")[0]
        found = await github.get(
            f"/repos/{slug}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open"},
        )
        found.raise_for_status()
        if found.json():
            return str(found.json()[0]["html_url"])
    made.raise_for_status()
    return str(made.json()["html_url"])


def git(
    repo: Path, *args: str, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """``git`` in ``repo``, with nobody to ask and ``GIT_SECONDS`` to
    answer, ``env`` added to the runner's; a refusal raises with what git
    said."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=check,
        timeout=GIT_SECONDS,
        env={**os.environ, **env} if env else None,
    )


def _fetch(repo: Path) -> None:
    """What the remote has now, where it can be reached in time."""
    with contextlib.suppress(subprocess.TimeoutExpired):
        git(repo, "fetch", "--quiet", check=False)


def _add(repo: Path, *how: str) -> None:
    """A worktree of ``repo`` added as ``how`` says, any that were deleted
    by hand forgotten first."""
    git(repo, "worktree", "prune", check=False)
    git(repo, "worktree", "add", "--quiet", *how)


def _has(repo: Path, ref: str) -> bool:
    return (
        git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0
    )


def place(repo: Path, home: Path, branch: str) -> Path:
    """Where ``branch``'s worktree is kept under ``home``: refused unless it
    is a branch name, and a place under ``home``."""
    if git(repo, "check-ref-format", "--branch", branch, check=False).returncode:
        raise WorktreeRefusedError(f"{branch!r} is no branch name")
    path = (home / branch).resolve()
    if not path.is_relative_to(home):
        raise WorktreeRefusedError(f"{branch!r} is no place under {home}")
    return path


def kept(repo: Path, ref: str, home: Path, branch: str) -> Path:
    """The worktree kept for ``branch`` under ``home``: found there, still
    on it, or made the first time, on the branch as the repository or its
    remote has it, else on a new one from ``ref``. ``branch`` is the app's
    word: only a branch name is taken (never an option to git), and only
    for a place under ``home`` (``place``)."""
    path = place(repo, home, branch)
    if (path / ".git").exists():
        on = git(path, "symbolic-ref", "--short", "--quiet", "HEAD", check=False)
        if on.stdout.strip() != branch:
            raise WorktreeRefusedError(
                f"{path} is on {on.stdout.strip() or 'no branch'}, not {branch}"
            )
        return path
    _fetch(repo)
    there = _has(repo, f"refs/heads/{branch}") or _has(
        repo, f"refs/remotes/origin/{branch}"
    )
    _add(
        repo,
        *(
            [str(path), branch]
            if there
            else ["--no-track", "-b", branch, str(path), ref]
        ),
    )
    return path


@contextmanager
def fresh(repo: Path, ref: str) -> Iterator[Path]:
    """A fresh worktree of ``repo`` at ``ref``, removed after."""
    _fetch(repo)
    with tempfile.TemporaryDirectory(prefix="runner-run-") as parent:
        path = Path(parent) / "worktree"
        _add(repo, "--detach", str(path), ref)
        try:
            yield path
        finally:
            git(repo, "worktree", "remove", "--force", str(path), check=False)
