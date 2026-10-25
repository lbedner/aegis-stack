"""Per-stack tests for the skills shipped inside generated projects.

Assert each stack ships exactly the skills matching its selection, that every
repo-relative path a shipped skill references exists in that stack (no dangling
references), and that the worker skill is rendered for the chosen backend.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

# A backtick-quoted, repo-relative path a shipped skill points at. Placeholder
# paths like `tests/api/test_<name>.py` do not match (the char class stops at
# `<`, so the closing backtick is never reached), so only concrete paths run.
_ROOTED_PATH = re.compile(r"`((?:app|tests|alembic)/[A-Za-z0-9_./-]+)`")

# Skills every stack ships (backend is core).
_ALWAYS = {
    "add-api-endpoint",
    "add-cli-command",
    "change-the-stack",
    "plan-with-the-twin",
}

# Extra skills expected per stack, on top of the always-on set. auth pulls in
# migrations, so it also gets add-model-and-migration.
_EXTRA_BY_STACK: dict[str, set[str]] = {
    "base": set(),
    "base_with_auth_service": {"protect-an-endpoint", "add-model-and-migration"},
    "base_with_worker": {"add-background-job"},
    "base_with_worker_dramatiq": {"add-background-job"},
    "base_with_worker_taskiq": {"add-background-job"},
    "base_with_scheduler": {"add-scheduled-job"},
}


def _shipped_skill_names(project: Path) -> set[str]:
    root = project / ".claude" / "skills"
    return {p.parent.name for p in root.glob("*/SKILL.md")}


def test_each_stack_ships_exactly_its_skills(
    project_factory: Callable[..., Path],
) -> None:
    for stack, extra in _EXTRA_BY_STACK.items():
        project = project_factory(name=stack)
        assert _shipped_skill_names(project) == _ALWAYS | extra, stack


def test_shipped_skills_have_no_dangling_paths(
    project_factory: Callable[..., Path],
) -> None:
    for stack in _EXTRA_BY_STACK:
        project = project_factory(name=stack)
        skills = sorted((project / ".claude" / "skills").glob("*/SKILL.md"))
        assert skills, f"{stack}: no skills shipped"
        for skill in skills:
            for path in _ROOTED_PATH.findall(skill.read_text()):
                target = project / path.rstrip("/")
                assert target.exists(), (
                    f"{stack}: {skill.parent.name} references missing path {path!r}"
                )


def test_background_job_skill_is_rendered_for_the_backend(
    project_factory: Callable[..., Path],
) -> None:
    # arq (default) stack.
    arq = project_factory(name="base_with_worker")
    arq_skill = (arq / ".claude/skills/add-background-job/SKILL.md").read_text()
    assert "arq" in arq_skill
    assert "{% if" not in arq_skill, "jinja not rendered"

    # dramatiq variant names its own idiom.
    dramatiq = project_factory(name="base_with_worker_dramatiq")
    dq_skill = (dramatiq / ".claude/skills/add-background-job/SKILL.md").read_text()
    assert "Dramatiq" in dq_skill or "dramatiq" in dq_skill
    assert ".send(" in dq_skill
