"""Phase B of issue #715 — 3-way merge for diverged shared files.

The #715 guard stopped `add-service`/`add-component` from clobbering
hand-edited shared files, but it could only *preserve and warn* — the new
component's wiring never reached a diverged file. Phase B upgrades the
diverged branch of `ManualUpdater._regenerate_shared_files` to a real
3-way merge:

    base   = template render at the project's *current* answers
    ours   = template render at the *updated* answers (the delta)
    theirs = the file on disk (with user edits)

Non-conflicting template changes are merged into the user's file
automatically. Overlapping changes produce git-style conflict markers and
are reported for manual resolution. Python files are normalized through
ruff first (so formatting noise doesn't create spurious conflicts); other
files merge as-is. If the merge can't run (git/ruff missing), it falls
back to the #715 preserve+warn behavior so nothing is ever clobbered.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from aegis.core import render_diff
from aegis.core.manual_updater import ManualUpdater
from tests.cli.conftest import ProjectFactory

# The 3-way merge shells out to ``ruff`` (3× normalize) and ``git
# merge-file`` per merged file. Under ``pytest -n auto``, those forks get
# starved by the subprocess-heavy ``generated_stacks`` tests on sibling
# workers (copier/uv bursts → EAGAIN), and the merge silently falls back to
# preserve, flaking these assertions. Pinning to the same xdist group puts
# them on the same worker as those heavy tests — loadgroup runs a worker's
# tests serially, so the merge never races the fork bursts; the other
# workers run lightweight unit tests. See the retry budget in
# ``manual_updater._run_ruff`` / ``template_cleanup.merge_three_way_text``.
pytestmark = pytest.mark.xdist_group("generated_stacks")

CONFIG_FILE = "app/core/config.py"
COMPOSE_FILE = "docker-compose.yml"


def _append(path, text: str) -> None:
    path.write_text(path.read_text().rstrip("\n") + "\n" + text)


class TestThreeWayMergeClean:
    """Non-overlapping template changes merge into diverged files."""

    def test_add_component_merges_template_change_into_edited_python_file(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base")  # no database
        config = project / CONFIG_FILE
        _append(config, "\n# PULSE_CUSTOM_MARKER\nPULSE_EXTRA = 'keep'\n")

        updater = ManualUpdater(project)
        updated, _, manual = updater._regenerate_shared_files(
            {**updater.answers, "include_database": True}
        )

        after = config.read_text()
        assert "PULSE_CUSTOM_MARKER" in after, "user edit was lost"
        assert "DATABASE_URL" in after, "template change was not merged in"
        assert "<<<<<<<" not in after, "clean merge should not leave conflict markers"
        assert CONFIG_FILE in updated
        assert CONFIG_FILE not in manual

    def test_remove_component_drops_block_but_keeps_user_edit(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base_with_database")
        config = project / CONFIG_FILE
        assert "DATABASE_URL" in config.read_text()
        _append(config, "\n# PULSE_CUSTOM_MARKER\nPULSE_EXTRA = 'keep'\n")

        updater = ManualUpdater(project)
        updated, _, _ = updater._regenerate_shared_files(
            {**updater.answers, "include_database": False}
        )

        after = config.read_text()
        assert "PULSE_CUSTOM_MARKER" in after, "user edit was lost on removal"
        assert "DATABASE_URL" not in after, "removed component block should be gone"
        assert "<<<<<<<" not in after
        assert CONFIG_FILE in updated

    def test_merges_non_python_file_without_ruff(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base")
        compose = project / COMPOSE_FILE
        _append(compose, "  pulse_sidecar:\n    image: custom:latest\n")

        updater = ManualUpdater(project)
        updated, _, _ = updater._regenerate_shared_files(
            {**updater.answers, "include_redis": True}
        )

        after = compose.read_text()
        assert "pulse_sidecar" in after, "user edit was lost"
        assert "redis" in after, "template change (redis service) was not merged in"
        assert COMPOSE_FILE in updated


class TestThreeWayMergeConflict:
    """Overlapping edits surface conflict markers instead of silent loss."""

    def test_overlapping_edit_produces_conflict_markers(
        self, project_factory: ProjectFactory
    ) -> None:
        project = project_factory("base_with_database")  # sqlite
        config = project / CONFIG_FILE
        lines = config.read_text().split("\n")
        for i, line in enumerate(lines):
            if 'DATABASE_URL: str = "sqlite' in line:
                lines[i] = '    DATABASE_URL: str = "sqlite:///./data/PULSE_CUSTOM.db"'
                break
        else:
            pytest.fail("fixture config.py missing sqlite DATABASE_URL line")
        config.write_text("\n".join(lines))

        updater = ManualUpdater(project)
        updated, _, manual = updater._regenerate_shared_files(
            {**updater.answers, "database_engine": "postgres"}
        )

        after = config.read_text()
        assert "<<<<<<<" in after, "overlapping edit should produce conflict markers"
        assert "PULSE_CUSTOM" in after, "user's side of the conflict must be present"
        assert "postgresql://" in after, (
            "template's side of the conflict must be present"
        )
        assert CONFIG_FILE in manual
        assert CONFIG_FILE not in updated


class TestThreeWayMergeFallback:
    """If the merge engine can't run, fall back to #715 preserve+warn."""

    @pytest.fixture
    def _no_merge(self) -> Iterator[None]:
        # Patch target moved with the RD-04 rewiring (aegis-stack#919):
        # the merge now runs inside the render-diff engine, so its module's
        # reference is the one that matters — patching manual_updater's
        # copy would silently intercept nothing and let a real merge run.
        original = render_diff.merge_three_way_text

        def boom(*_args: object, **_kwargs: object) -> tuple[int, str]:
            return (-1, "")  # simulate git merge-file unavailable/failed

        render_diff.merge_three_way_text = boom  # type: ignore[assignment]
        try:
            yield
        finally:
            render_diff.merge_three_way_text = original  # type: ignore[assignment]

    def test_falls_back_to_preserve_when_merge_unavailable(
        self, project_factory: ProjectFactory, _no_merge: None
    ) -> None:
        project = project_factory("base")
        config = project / CONFIG_FILE
        _append(config, "\n# PULSE_CUSTOM_MARKER\nPULSE_EXTRA = 'keep'\n")
        before = config.read_text()

        updater = ManualUpdater(project)
        _, _, manual = updater._regenerate_shared_files(
            {**updater.answers, "include_database": True}
        )

        assert config.read_text() == before, "file must be untouched on fallback"
        assert CONFIG_FILE in manual

    def test_ruff_failure_preserves_file_instead_of_writing_bad_output(
        self, project_factory: ProjectFactory
    ) -> None:
        """If ruff can't normalize a file (e.g. user left a syntax error),
        the merge must bail and preserve the file rather than write
        partially/unformatted output. Guards the _run_ruff failure contract.
        """
        project = project_factory("base")
        config = project / CONFIG_FILE
        _append(config, "\ndef this_is( # deliberately unparseable\n")
        before = config.read_text()

        updater = ManualUpdater(project)
        # Sanity: ruff normalization reports failure on the broken file
        # (same call the engine's merge path makes).
        from aegis.core.template_cleanup import run_ruff_on_text

        assert run_ruff_on_text(before, project, "I", CONFIG_FILE) is None

        _, _, manual = updater._regenerate_shared_files(
            {**updater.answers, "include_database": True}
        )

        assert config.read_text() == before, "file must be untouched when ruff fails"
        assert CONFIG_FILE in manual
