"""``--shard K/N``: run the K-th of N slices of the selected tests.

CI runs the suite as parallel jobs, one slice each (.github/workflows/ci.yml).
Tests split by file, largest first into the lightest slice, so the slices
come out even in size; every job collects the same tests, so they agree on
the split. An ``xdist_group`` stays in one slice, because its tests are
pinned to one worker on purpose.

conftest.py imports the two hooks, which is what registers them.
"""

import re
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--shard",
        default=None,
        metavar="K/N",
        help="run only the K-th of N parallel slices of the selected tests (CI)",
    )


def parse_shard(spec: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)/(\d+)", spec)
    if not match or not 1 <= int(match[1]) <= int(match[2]):
        raise pytest.UsageError(f"--shard expects K/N with 1 <= K <= N, got {spec!r}")
    return int(match[1]), int(match[2])


def shard_key(item: Any) -> str:
    group = item.get_closest_marker("xdist_group")
    if group is not None:
        return f"group:{group.args[0]}"
    return item.nodeid.split("::")[0]


def pytest_collection_modifyitems(config: pytest.Config, items: list[Any]) -> None:
    spec = config.getoption("--shard")
    if not spec:
        return
    k, n = parse_shard(spec)
    groups: dict[str, list[Any]] = {}
    for item in items:
        groups.setdefault(shard_key(item), []).append(item)
    sizes = [0] * n
    mine: set[str] = set()
    for key in sorted(groups, key=lambda key: (-len(groups[key]), key)):
        lightest = sizes.index(min(sizes))
        sizes[lightest] += len(groups[key])
        if lightest == k - 1:
            mine.add(key)
    keep = [item for item in items if shard_key(item) in mine]
    drop = [item for item in items if shard_key(item) not in mine]
    items[:] = keep
    config.hook.pytest_deselected(items=drop)
