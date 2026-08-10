"""Merge-unavailable safety net for the render-diff engine.

Found during a pre-RD-04 review of ``_merge`` against the reference
implementation it mirrored (``ManualUpdater._merge_shared_file``, since
deleted — the engine is now the only merge path): two failure paths were
unguarded.

1. ``merge_three_way_text`` returns ``(-1, "")`` when ``git merge-file``
   itself is unavailable/erroring — the OLD reference treats that as
   "could not merge, preserve the file" (never writes ``""`` to disk).
   The engine's ``_merge`` ignored the returncode entirely and would have
   happily written the empty string as if it were a clean merge.
2. The OLD reference bails to "preserve" if ANY of the three ruff
   normalizations fail for a ``.py`` file — never merges on a mix of
   normalized and raw content, since that reintroduces the formatting
   noise the normalization exists to remove. The engine's ``_merge``
   silently fell through to raw content instead.

Both are untested-in-practice failure paths (git/ruff are always present
in dev/CI), which is exactly why a targeted, monkeypatched test is the
only way to exercise them before this engine is wired into anything real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core import render_diff
from aegis.core.render_diff import FileAction, RenderDiffEngine
from tests.core.conftest import make_render_diff_engine
from tests.core.conftest import write_template_file as _write

PROJECT_SLUG = "{{ project_slug }}"


@pytest.fixture
def engine(tmp_path: Path) -> RenderDiffEngine:
    root = tmp_path / "template"
    _write(
        root / PROJECT_SLUG / "plain.py.jinja",
        "def before() -> None:\n"
        "    pass\n"
        "\n"
        "\n"
        "def value() -> str:\n"
        '    return "{{ label }}"\n'
        "\n"
        "\n"
        "def after() -> None:\n"
        "    pass\n",
    )
    return make_render_diff_engine(root, tmp_path)


def _diverge(engine: RenderDiffEngine) -> None:
    """A real user edit that would otherwise merge cleanly."""
    (engine.project_path / "plain.py").write_text(
        "def before() -> None:\n"
        '    """User docstring."""\n'
        "    pass\n"
        "\n"
        "\n"
        "def value() -> str:\n"
        '    return "old"\n'
        "\n"
        "\n"
        "def after() -> None:\n"
        "    pass\n"
    )


class TestGitUnavailableDuringMerge:
    def test_does_not_write_empty_content(
        self, engine: RenderDiffEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """git merge-file missing/erroring must never be treated as a
        clean empty merge — that would silently truncate the user's file."""
        _diverge(engine)
        monkeypatch.setattr(
            render_diff, "merge_three_way_text", lambda *_args, **_kwargs: (-1, "")
        )

        plans = engine.plan({"label": "old"}, {"label": "new"})
        plan = next(p for p in plans if p.rel_path == "plain.py")

        assert plan.action == FileAction.PRESERVE, (
            f"expected PRESERVE when git is unavailable, got {plan.action} "
            f"with content={plan.content!r}"
        )

    def test_apply_leaves_file_on_disk_untouched(
        self, engine: RenderDiffEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _diverge(engine)
        original = (engine.project_path / "plain.py").read_text()
        monkeypatch.setattr(
            render_diff, "merge_three_way_text", lambda *_args, **_kwargs: (-1, "")
        )

        plans = engine.plan({"label": "old"}, {"label": "new"})
        result = engine.apply(plans)

        assert "plain.py" in result.preserved
        assert (engine.project_path / "plain.py").read_text() == original


class TestRuffUnavailableDuringMerge:
    def test_partial_ruff_failure_falls_back_to_preserve(
        self, engine: RenderDiffEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If even ONE of the three ruff normalizations fails, merging on
        a mix of normalized and raw content reintroduces the formatting
        noise the normalization exists to remove — must preserve instead,
        never merge on inconsistent inputs."""
        _diverge(engine)

        # ``_pristine`` also calls ``run_ruff_on_text`` (check_select="")
        # before ``_merge`` ever runs (check_select="I"), so a plain call
        # counter targets the wrong call. Discriminate on check_select
        # instead: fail only the second of _merge's three "I"-mode calls.
        real_run_ruff_on_text = render_diff.run_ruff_on_text
        i_mode_calls = {"n": 0}

        def flaky(
            src: str,
            project_path: Path,
            check_select: str | None,
            rel_path: str | None = None,
        ) -> str | None:
            if check_select == "I":
                i_mode_calls["n"] += 1
                if i_mode_calls["n"] == 2:
                    return None
            return real_run_ruff_on_text(src, project_path, check_select, rel_path)

        monkeypatch.setattr(render_diff, "run_ruff_on_text", flaky)

        plans = engine.plan({"label": "old"}, {"label": "new"})
        plan = next(p for p in plans if p.rel_path == "plain.py")

        assert plan.action == FileAction.PRESERVE
