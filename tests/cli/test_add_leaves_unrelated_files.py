"""``aegis add`` writes what the component changes, not the rest of a
newer template.

A project generated from one checkout and added to from a newer one (both
called 0.16.1, so the version gate passed) gained every file the newer
template had and it did not: 59 of them, among them the tests of a
dashboard feature whose code never came, failing CI. A file the add does
not change is ``aegis update``'s to bring, with the files it goes with
(aegis-stack#2029). That includes CLAUDE.md's always-on skills for a
project that predates them (SK-12).
"""

from __future__ import annotations

import pytest

from aegis.core.manual_updater import ManualUpdater
from tests.cli.conftest import ProjectFactory

pytestmark = pytest.mark.xdist_group("generated_stacks")

UNCHANGED_BY_REDIS = (
    "app/core/cpus.py",
    ".claude/skills/add-api-endpoint/SKILL.md",
    ".claude/skills/add-cli-command/SKILL.md",
    ".claude/skills/change-the-stack/SKILL.md",
    ".claude/skills/plan-with-the-twin/SKILL.md",
)
"""Shared by every stack, and the same with redis or without."""

SCHEDULER_OR_WORKER = (
    "tests/services/test_component_integration.py",
    "tests/services/test_health_logic.py",
)
"""A stack has these once it has a scheduler or a worker."""


@pytest.mark.parametrize("rel_path", UNCHANGED_BY_REDIS)
def test_an_add_does_not_backfill_a_file_it_does_not_change(
    project_factory: ProjectFactory, rel_path: str
) -> None:
    project = project_factory("base")
    (project / rel_path).unlink()

    updater = ManualUpdater(project)
    updated, _, _ = updater._regenerate_shared_files(
        {**updater.answers, "include_redis": True}
    )

    assert not (project / rel_path).exists()
    assert rel_path not in updated


def test_an_add_creates_the_shared_files_its_gate_turns_on(
    project_factory: ProjectFactory,
) -> None:
    """Their template says when a stack has them, so the add that turns
    the condition on writes them, as init would have."""
    project = project_factory("base")
    assert not any((project / p).exists() for p in SCHEDULER_OR_WORKER)

    updater = ManualUpdater(project)
    updated, _, _ = updater._regenerate_shared_files(
        {**updater.answers, "include_scheduler": True}
    )

    for rel_path in SCHEDULER_OR_WORKER:
        assert (project / rel_path).is_file(), f"{rel_path} was not created"
        assert rel_path in updated
