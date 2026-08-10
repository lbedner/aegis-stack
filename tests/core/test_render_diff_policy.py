"""Tests for template-header policy annotations (RD-02, aegis-stack#917).

``{# aegis: <word> #}`` on a template's first line is the engine's only
per-file policy mechanism — no central override map. See
``aegis/core/render_diff.py`` module docstring for the vocabulary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core.render_diff import (
    FileAction,
    FilePolicy,
    RenderDiffEngine,
    _read_policy_and_body,
)
from tests.core.conftest import make_render_diff_engine
from tests.core.conftest import write_template_file as _write

PROJECT_SLUG = "{{ project_slug }}"


@pytest.fixture
def template_root(tmp_path: Path) -> Path:
    root = tmp_path / "template"
    slug_dir = root / PROJECT_SLUG

    _write(
        slug_dir / "readme.md.jinja",
        "{#- aegis: user-owned -#}\n# {{ project_name }}\n",
    )
    _write(
        slug_dir / "dockerfile.jinja",
        "{#- aegis: warn-if-diverged -#}\nFROM python:{{ python_version }}\n",
    )
    _write(
        slug_dir / "derived.py.jinja",
        '{#- aegis: no-backup -#}\nVALUE = "{{ label }}"\n',
    )
    _write(
        slug_dir / "plain.py.jinja",
        'VALUE = "{{ label }}"\n',
    )

    return root


@pytest.fixture
def engine(template_root: Path, tmp_path: Path) -> RenderDiffEngine:
    return make_render_diff_engine(template_root, tmp_path)


@pytest.fixture
def engine_with_typo(tmp_path: Path) -> RenderDiffEngine:
    """A separate tree carrying only the invalid-annotation file, so a
    typo in one template doesn't blow up ``plan()`` for every other test
    sharing the main fixture tree."""
    typo_root = tmp_path / "typo_template"
    _write(
        typo_root / PROJECT_SLUG / "typo.py.jinja",
        "{#- aegis: nonexistent-policy -#}\nVALUE = 1\n",
    )
    return make_render_diff_engine(typo_root, tmp_path)


class TestAnnotationParsing:
    def test_no_annotation_is_default_policy(self) -> None:
        policy, body = _read_policy_and_body('VALUE = "{{ label }}"\n')
        assert policy == FilePolicy.DEFAULT
        assert body == 'VALUE = "{{ label }}"\n'

    @pytest.mark.parametrize(
        "word,expected",
        [
            ("user-owned", FilePolicy.USER_OWNED),
            ("warn-if-diverged", FilePolicy.WARN_IF_DIVERGED),
            ("no-backup", FilePolicy.NO_BACKUP),
        ],
    )
    def test_each_vocabulary_word_parses_and_strips(
        self, word: str, expected: FilePolicy
    ) -> None:
        source = f"{{#- aegis: {word} -#}}\nBODY\n"
        policy, body = _read_policy_and_body(source)
        assert policy == expected
        assert body == "BODY\n"
        assert "aegis:" not in body

    def test_unknown_word_raises(self) -> None:
        with pytest.raises(ValueError, match="nonexistent-policy"):
            _read_policy_and_body("{#- aegis: nonexistent-policy -#}\nBODY\n")

    def test_missing_trim_markers_raises(self) -> None:
        """A recognized word without ``{#- ... -#}`` trim markers must fail
        loudly rather than silently rendering a stray blank line under
        plain Jinja (init/update haven't been rewired onto this engine
        yet, so they still render the raw comment as-is)."""
        with pytest.raises(ValueError, match="whitespace-trim"):
            _read_policy_and_body("{# aegis: no-backup #}\nBODY\n")

    def test_annotation_never_appears_in_rendered_output(
        self, engine: RenderDiffEngine
    ) -> None:
        content = engine._render("readme.md", {"project_name": "demo"})
        assert "aegis:" not in content
        assert content == "# demo\n"

    def test_annotated_and_unannotated_render_identically_otherwise(
        self, engine: RenderDiffEngine
    ) -> None:
        """The annotation's only effect is policy — not rendered content."""
        annotated = engine._render("derived.py", {"label": "x"})
        plain = engine._render("plain.py", {"label": "x"})
        assert annotated == plain


class TestUserOwnedPolicy:
    def test_created_once_when_missing(self, engine: RenderDiffEngine) -> None:
        plans = {
            p.rel_path: p
            for p in engine.plan({"project_name": "a"}, {"project_name": "b"})
        }
        assert plans["readme.md"].action == FileAction.CREATE

    def test_never_overwritten_once_diverged(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "readme.md").write_text("# Hand-written by a human\n")
        plans = {
            p.rel_path: p
            for p in engine.plan({"project_name": "a"}, {"project_name": "b"})
        }
        assert plans["readme.md"].action == FileAction.PRESERVE

    def test_never_deleted(self, engine: RenderDiffEngine) -> None:
        """Even if the operation would otherwise consider this file gone
        (base non-empty, ours empty), user-owned content is never removed."""
        (engine.project_path / "readme.md").write_text("# Hand-written by a human\n")
        plans = {
            p.rel_path: p
            for p in engine.plan({"project_name": "a"}, {"project_name": ""})
        }
        assert plans["readme.md"].action == FileAction.PRESERVE

    def test_apply_leaves_file_untouched(self, engine: RenderDiffEngine) -> None:
        original = "# Hand-written by a human\n"
        (engine.project_path / "readme.md").write_text(original)
        plans = engine.plan({"project_name": "a"}, {"project_name": "b"})
        result = engine.apply(plans)

        assert "readme.md" in result.preserved
        assert (engine.project_path / "readme.md").read_text() == original


class TestWarnIfDivergedPolicy:
    def test_pristine_is_overwritten(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "dockerfile").write_text(
            engine._render("dockerfile", {"python_version": "3.12"})
        )
        plans = {
            p.rel_path: p
            for p in engine.plan({"python_version": "3.12"}, {"python_version": "3.13"})
        }
        assert plans["dockerfile"].action == FileAction.OVERWRITE

    def test_diverged_is_preserved_not_merged(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "dockerfile").write_text(
            "FROM python:3.12\nRUN custom-build-step.sh\n"
        )
        plans = {
            p.rel_path: p
            for p in engine.plan({"python_version": "3.12"}, {"python_version": "3.13"})
        }
        assert plans["dockerfile"].action == FileAction.PRESERVE

    def test_diverged_but_operation_does_not_change_file_is_skipped(
        self, engine: RenderDiffEngine
    ) -> None:
        """Old behavior (``_regenerate_shared_files``): only warn when this
        operation actually changes the file's target content."""
        (engine.project_path / "dockerfile").write_text(
            "FROM python:3.12\nRUN custom-build-step.sh\n"
        )
        plans = {
            p.rel_path: p
            for p in engine.plan({"python_version": "3.12"}, {"python_version": "3.12"})
        }
        assert plans["dockerfile"].action == FileAction.SKIP


class TestNoBackupPolicy:
    def test_overwrite_skips_backup_file(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "derived.py").write_text(
            engine._render("derived.py", {"label": "old"})
        )
        plans = engine.plan({"label": "old"}, {"label": "new"})
        result = engine.apply(plans, backup=True)

        assert "derived.py" in result.overwritten
        assert "derived.py" not in result.backed_up
        assert not (engine.project_path / "derived.py.backup").exists()

    def test_default_policy_still_backs_up(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "plain.py").write_text(
            engine._render("plain.py", {"label": "old"})
        )
        plans = engine.plan({"label": "old"}, {"label": "new"})
        result = engine.apply(plans, backup=True)

        assert "plain.py" in result.overwritten
        assert "plain.py" in result.backed_up


class TestInvalidAnnotationFailsLoudly:
    def test_unknown_annotation_raises_on_render(
        self, engine_with_typo: RenderDiffEngine
    ) -> None:
        with pytest.raises(ValueError, match="nonexistent-policy"):
            engine_with_typo._render("typo.py", {})

    def test_unknown_annotation_raises_during_plan(
        self, engine_with_typo: RenderDiffEngine
    ) -> None:
        with pytest.raises(ValueError, match="nonexistent-policy"):
            engine_with_typo.plan({}, {})
