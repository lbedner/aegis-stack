"""SK-12: agent files reach projects that predate them.

A project generated before skills existed has no CLAUDE.md and no .claude/skills.
The shared-file regeneration path (run on add/remove/update) must CREATE these,
not just overwrite existing ones, so older projects become agent-ready.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from tests.cli.test_utils import run_aegis_command


def test_regeneration_creates_missing_agent_files(
    project_factory: Callable[..., Path],
) -> None:
    project = project_factory("base")

    # Simulate a project generated before skills existed.
    (project / "CLAUDE.md").unlink()
    shutil.rmtree(project / ".claude")
    assert not (project / "CLAUDE.md").exists()
    assert not (project / ".claude").exists()

    # Any component add runs the shared-file regeneration path.
    result = run_aegis_command("add", "redis", "--project-path", str(project), "--yes")
    assert result.returncode == 0, f"add redis failed: {result.stderr}"

    # The pre-skills project gains the selection-aware CLAUDE.md and the
    # always-on skills.
    assert (project / "CLAUDE.md").exists(), "update did not create CLAUDE.md"
    for skill in (
        "add-api-endpoint",
        "add-cli-command",
        "change-the-stack",
        "plan-with-the-twin",
    ):
        assert (project / ".claude/skills" / skill / "SKILL.md").exists(), (
            f"update did not create the {skill} skill"
        )
