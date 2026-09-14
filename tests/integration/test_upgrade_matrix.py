"""Upgrading is not one path. It is a stack shape crossed with the version
someone starts from, and the failures live in the combination: a service
whose questions did not exist at the starting version, a component whose
files moved since, an answer added in between that nothing carries forward.

The rest of the update suite proves the mechanism on one stack from one
commit, which is the right shape for testing the mechanism and the wrong
shape for testing coverage. This sweeps the stacks people actually run,
from the releases they are actually on, and asserts the only outcome that
matters to them: the update finishes and leaves nothing to hand-resolve.

Slow by construction (one generate plus one update per pair), so it runs in
the nightly slow suite rather than on every PR.
"""

import subprocess
from pathlib import Path

import pytest
import yaml

from .test_update_integration import find_rej_files, run_update

pytestmark = [pytest.mark.slow, pytest.mark.integration]

# How many releases back to start from. Derived from the tags rather than
# written down, so the sweep follows the release history instead of going
# stale the first time nobody remembers to edit it.
RELEASES_BACK = 3

# Stack shapes, named by what they exercise. Deliberately small: every pair
# is a full generate plus a full update, and the axis that finds bugs is
# the version, not the twentieth variation on a service list. Each piece
# here has existed for longer than RELEASES_BACK releases, so a pair can
# only fail for a real reason rather than because the old template never
# had the question.
STACKS: dict[str, list[str]] = {
    "base": [],
    "components": ["--components", "database,worker,scheduler"],
    "services": ["--components", "database", "--services", "auth,ai[sqlite]"],
}


def _release_versions(template_root: Path, count: int) -> list[str]:
    """The last ``count`` released versions, newest first, rc tags excluded."""
    result = subprocess.run(
        ["git", "tag", "--list", "v[0-9]*", "--sort=-v:refname"],
        cwd=template_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    tags = [tag for tag in result.stdout.split() if "rc" not in tag]
    return [tag.lstrip("v") for tag in tags[:count]]


FROM_VERSIONS = _release_versions(Path(__file__).parents[2], RELEASES_BACK)


def _marker_files(project: Path) -> list[Path]:
    """Files left carrying ``<<<<<<<`` conflict markers.

    Scanned here rather than through the product's own scanner: a test that
    asks the tool whether the tool found anything proves nothing when the
    scanner is what broke.
    """
    skip = {".git", ".venv", "node_modules", "__pycache__"}
    found: list[Path] = []
    for path in project.rglob("*"):
        if not path.is_file() or skip & set(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(line.startswith("<<<<<<<") for line in text.splitlines()):
            found.append(path.relative_to(project))
    return found


def _init_at_version(parent: Path, name: str, version: str, args: list[str]) -> Path:
    """Generate a project from the template as it stood at ``version``."""
    result = subprocess.run(
        ["aegis", "init", name, "--to-version", version, "--no-interactive", "--yes"]
        + args,
        cwd=parent,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"init at {version} failed for this stack:\n"
            f"{result.stdout[-3000:]}\n{result.stderr[-2000:]}"
        )
    return parent / name


@pytest.mark.skipif(not FROM_VERSIONS, reason="no release tags (shallow clone)")
@pytest.mark.parametrize("from_version", FROM_VERSIONS)
@pytest.mark.parametrize("stack", sorted(STACKS))
def test_update_from_release_leaves_nothing_to_resolve(
    tmp_path: Path,
    template_path: Path,
    stack: str,
    from_version: str,
) -> None:
    """A supported project updates to HEAD without hand work.

    The three assertions are the three ways a user finds out it did not:
    the command fails, a ``.rej`` file appears, or a file is left carrying
    conflict markers that break the next thing they run.
    """
    project = _init_at_version(
        tmp_path, f"upgrade-{stack}", from_version, STACKS[stack]
    )

    result = run_update(project, template_path)

    assert result.returncode == 0, (
        f"{stack} from {from_version} failed to update:\n"
        f"{result.stdout[-3000:]}\n{result.stderr[-2000:]}"
    )
    assert find_rej_files(project) == []
    assert _marker_files(project) == []


@pytest.mark.skipif(not FROM_VERSIONS, reason="no release tags (shallow clone)")
@pytest.mark.parametrize("from_version", FROM_VERSIONS)
def test_update_advances_the_recorded_version(
    tmp_path: Path,
    template_path: Path,
    from_version: str,
) -> None:
    """The baseline moves, or the next update re-applies the same diff.

    One stack is enough: the advance is per-project bookkeeping, not
    per-stack behavior, and the expensive axis is already swept above.
    """
    project = _init_at_version(tmp_path, "upgrade-stamp", from_version, [])

    result = run_update(project, template_path)
    assert result.returncode == 0, result.stdout[-3000:]

    answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
    assert answers["_template_version"] != from_version, (
        "the recorded template version did not move off the starting release"
    )


# The pair above generates its "old" project with TODAY's CLI pointed at an
# old template tag, so the project gets today's model-derived revisions -
# not the revision FILES that release actually shipped. That is a different
# project from the one a user has, and the difference hides a whole class of
# bug: anything the new code does with the old revisions on disk.
#
# It hid one. A 0.10.1 project with auth + ai[sqlite] could not update at
# all, because the generator emitted `create_index(if_not_exists=True)`
# inside a `batch_alter_table` block and alembic's batch implementation
# takes no such argument. Every pair above passed while that was true.
#
# So one pair generates the project the way the user got it: by running the
# published CLI of that release. Network-dependent and slower, hence one.
PUBLISHED_FROM = "0.10.1"
PUBLISHED_STACK = ["--components", "database", "--services", "auth,ai[sqlite]"]


def test_update_from_a_published_release_leaves_nothing_to_resolve(
    tmp_path: Path,
    template_path: Path,
) -> None:
    """The project as the user has it: generated by the released CLI itself."""
    name = "published-upgrade"
    install = subprocess.run(
        [
            "uvx",
            f"aegis-stack@{PUBLISHED_FROM}",
            "init",
            name,
            *PUBLISHED_STACK,
            "--no-interactive",
            "-y",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        pytest.skip(
            f"cannot install aegis-stack {PUBLISHED_FROM}: {install.stderr[-500:]}"
        )

    project = tmp_path / name
    result = run_update(project, template_path, "--to-version", "HEAD")

    assert result.returncode == 0, (
        f"a published {PUBLISHED_FROM} project cannot update:\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-2000:]}"
    )
    assert find_rej_files(project) == []
    assert _marker_files(project) == []
