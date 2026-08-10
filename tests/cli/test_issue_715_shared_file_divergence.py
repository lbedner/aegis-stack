"""Regression tests for issue #715 — shared-file regen clobbers user edits.

``ManualUpdater._regenerate_shared_files`` re-renders every shared template
file from defaults and overwrites the project's copy. On a project that has
diverged from the template (hand-edited ``deps.py``, custom ``pyproject``
sections, etc.) this destroys those customizations.

The fix makes regen *divergence-aware*: a shared file is only overwritten
when the project's copy still matches what the template produces for the
project's current configuration. Edited files are preserved and reported
for manual merge.

The divergence check is formatting-insensitive. It compares against the
template render, falling back to a symmetric ruff normalization for Python
files so a ``make fix``-formatted-but-otherwise-pristine file is still
correctly treated as pristine (and regenerated), rather than being mistaken
for a user edit on the strength of import-merging or quote normalization.
"""

from __future__ import annotations

import subprocess

import pytest

from aegis.core.manual_updater import ManualUpdater
from aegis.core.template_cleanup import ruff_executable
from tests.cli.conftest import ProjectFactory

# Shares the merge path (``_regenerate_shared_files`` → ruff + git
# merge-file), so it has the same subprocess-contention flake risk as the
# 3-way-merge suite. Pin to the same xdist group to serialize it away from
# the fork-heavy ``generated_stacks`` tests. See the sibling file's note.
pytestmark = pytest.mark.xdist_group("generated_stacks")

DEPS_FILE = "app/components/backend/api/deps.py"
CONFIG_FILE = "app/core/config.py"
MARKER = "PULSE_CUSTOM_get_goal_service"


class TestDivergedSharedFilesPreserved:
    """User customizations to shared files must survive regeneration."""

    def test_diverged_python_shared_file_is_preserved(
        self, project_factory: ProjectFactory
    ) -> None:
        # No answer delta -> the operation doesn't change this file, so a
        # hand-edited shared file must be left byte-for-byte untouched.
        project = project_factory("base_with_auth_service")
        deps = project / DEPS_FILE
        deps.write_text(
            deps.read_text() + f"\n\ndef {MARKER}() -> str:\n"
            '    """Project-specific dependency provider."""\n'
            '    return "goal"\n'
        )
        before = deps.read_text()

        updater = ManualUpdater(project)
        updater._regenerate_shared_files(updater.answers)

        assert deps.read_text() == before, (
            "regen clobbered/rewrote a hand-edited shared file (issue #715)"
        )

    def test_diverged_text_shared_file_is_preserved(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base_with_auth_service")
        pyproject = project / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text() + "\n[tool.pulse.custom]\nkeep_me = true\n"
        )
        before = pyproject.read_text()

        updater = ManualUpdater(project)
        updater._regenerate_shared_files(updater.answers)

        assert pyproject.read_text() == before


class TestPristineSharedFilesStillRegenerate:
    """The guard must not block regeneration of untouched shared files.

    Both tests pass a genuinely different answers dict (``include_redis``
    flips) rather than ``updater.answers`` unchanged — a no-op self-diff
    means the operation touches nothing (BASE == OURS for every file), so
    it correctly reports nothing regenerated. That's not what these tests
    are checking; they need a real change to CONFIG_FILE's content to
    verify the pristine-file path still regenerates it.
    """

    def test_pristine_shared_file_is_regenerated(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base_with_auth_service")
        updater = ManualUpdater(project)

        updated, _, need_merge = updater._regenerate_shared_files(
            {**updater.answers, "include_redis": True}
        )

        assert CONFIG_FILE in updated
        assert CONFIG_FILE not in need_merge

    @pytest.mark.slow
    def test_make_fix_formatted_file_is_still_pristine(
        self, project_factory: ProjectFactory
    ) -> None:
        """A ruff-formatted-but-unedited file must NOT be seen as diverged.

        Whitespace-only normalization would false-positive here once a
        project has been through ``make fix`` (import merging, quote
        normalization, line wrapping). The detector must look through that.
        """
        ruff = ruff_executable()
        if ruff is None:
            pytest.skip("ruff not available")
        assert ruff is not None  # narrow for the type checker (skip isn't NoReturn)
        project = project_factory("base_with_auth_service")
        config = project / CONFIG_FILE
        # Format in place the way `make fix` would, without editing content.
        subprocess.run(
            [ruff, "check", "--fix", "--quiet", str(config)],
            cwd=project,
            capture_output=True,
        )
        subprocess.run(
            [ruff, "format", "--quiet", str(config)],
            cwd=project,
            capture_output=True,
        )

        updater = ManualUpdater(project)
        updated, _, need_merge = updater._regenerate_shared_files(
            {**updater.answers, "include_redis": True}
        )

        assert CONFIG_FILE in updated, (
            "formatting-only changes were misdetected as divergence"
        )
        assert CONFIG_FILE not in need_merge
