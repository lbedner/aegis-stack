"""``--shard K/N`` splits a run into N parallel CI jobs that add up to one.

Every test lands in exactly one shard, and what must share a process stays
together: a stack's generation tests (one ``aegis init`` per stack, reused),
and an ``xdist_group`` (pinned together on purpose).
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TARGET = "tests/cli/test_stack_generation.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    # The repo's addopts carry -v, which turns -q's node ids into a tree.
    return subprocess.run(
        [sys.executable, "-m", "pytest", TARGET, "--collect-only", "-q"]
        + ["-o", "addopts=", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
    )


def _collect(*args: str) -> set[str]:
    result = _run(*args)
    assert result.returncode == 0, result.stdout + result.stderr
    return {line for line in result.stdout.splitlines() if "::" in line}


@pytest.mark.parametrize("shards", [2, 4])
def test_the_shards_add_up_and_keep_each_stack_together(shards: int) -> None:
    everything = _collect()
    assert len(everything) > 100  # the matrix, not an empty parse
    parts = [_collect("--shard", f"{k}/{shards}") for k in range(1, shards + 1)]

    assert set().union(*parts) == everything
    assert sum(len(part) for part in parts) == len(everything)
    # A stack's tests reuse its single generation, so they share a shard.
    shard_of: dict[str, set[int]] = {}
    for index, part in enumerate(parts):
        for node in part:
            stack = re.search(r"\[([^\]]+)\]$", node)
            if stack:
                shard_of.setdefault(stack.group(1), set()).add(index)
    assert shard_of and all(len(found) == 1 for found in shard_of.values())


def test_a_malformed_shard_is_refused() -> None:
    result = _run("--shard", "3/2")

    assert result.returncode != 0
    assert "--shard" in result.stdout + result.stderr
