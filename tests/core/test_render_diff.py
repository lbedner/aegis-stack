"""Tests for the answers-diff render engine (RD-01, aegis-stack#916).

Uses a small fixture template tree instead of the real aegis templates so
each classification row in the engine's decision table is isolated:

    absent/empty in BASE, present in OURS   -> create
    present in BASE, empty/absent in OURS   -> delete if pristine, else preserve
    BASE == OURS                            -> skip
    pristine (THEIRS == BASE)               -> overwrite
    else                                    -> merge (clean or conflict)

See ``aegis/core/render_diff.py`` for the engine itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core.render_diff import FileAction, RenderDiffEngine
from aegis.core.template_cleanup import ruff_executable
from tests.core.conftest import make_render_diff_engine
from tests.core.conftest import write_template_file as _write

PROJECT_SLUG = "{{ project_slug }}"


@pytest.fixture
def template_root(tmp_path: Path) -> Path:
    """A tiny template tree exercising: verbatim copy, a whole-file Jinja
    gate, and an unconditional file whose content depends on an answer."""
    root = tmp_path / "template"
    slug_dir = root / PROJECT_SLUG

    _write(slug_dir / "always.txt", 'print("{{ not_a_jinja_var }}")\n')

    _write(
        slug_dir / "gated.py.jinja",
        "{% if include_thing %}\ndef handler() -> None:\n    pass\n{% endif %}\n",
    )

    _write(
        slug_dir / "plain.py.jinja",
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

    _write(
        slug_dir / "unconditional.py.jinja",
        "CONST = 1\n",
    )

    _write(slug_dir / "__init__.py.jinja", "")

    return root


@pytest.fixture
def engine(template_root: Path, tmp_path: Path) -> RenderDiffEngine:
    return make_render_diff_engine(template_root, tmp_path)


def _plan_for(engine: RenderDiffEngine, old: dict, new: dict, rel_path: str):
    plans = {p.rel_path: p for p in engine.plan(old, new)}
    assert rel_path in plans, f"{rel_path} missing from plan: {sorted(plans)}"
    return plans[rel_path]


class TestDiscovery:
    def test_discovers_every_template_path(self, engine: RenderDiffEngine) -> None:
        paths = set(engine.discover_paths())
        assert paths == {
            "always.txt",
            "gated.py",
            "plain.py",
            "unconditional.py",
            "__init__.py",
        }

    def test_skips_binary_assets(self, engine: RenderDiffEngine) -> None:
        """A PNG in the template tree must never be read_text()'d — that
        raises UnicodeDecodeError the moment anything renders it."""
        binary_path = engine.template_root / PROJECT_SLUG / "logo.png"
        binary_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

        assert "logo.png" not in engine.discover_paths()

    def test_skips_pycache_artifacts(self, engine: RenderDiffEngine) -> None:
        """A stray __pycache__ dir under the template tree (from someone
        importing its raw .py files directly) is not authored content."""
        pyc_path = (
            engine.template_root
            / PROJECT_SLUG
            / "__pycache__"
            / "gated.cpython-313.pyc"
        )
        pyc_path.parent.mkdir(parents=True, exist_ok=True)
        pyc_path.write_bytes(b"\x00\x00\x00\x00")

        paths = engine.discover_paths()
        assert not any("__pycache__" in p for p in paths)


class TestPlanScoping:
    """A caller (RD-04's ManualUpdater) must be able to scope plan() to an
    explicit subset — e.g. paths no component/service manifest owns — so
    the engine never classifies files outside that scope at all."""

    def test_plan_defaults_to_discover_paths(self, engine: RenderDiffEngine) -> None:
        plans = engine.plan({"include_thing": False}, {"include_thing": True})
        assert {p.rel_path for p in plans} == set(engine.discover_paths())

    def test_explicit_paths_restricts_the_plan(self, engine: RenderDiffEngine) -> None:
        plans = engine.plan(
            {"include_thing": False},
            {"include_thing": True},
            paths=["gated.py", "plain.py"],
        )
        assert {p.rel_path for p in plans} == {"gated.py", "plain.py"}

    def test_explicit_paths_never_touches_excluded_files(
        self, engine: RenderDiffEngine
    ) -> None:
        """A path outside the scope must not be classified, rendered, or
        written — even if it would otherwise need a backfill-create."""
        plans = engine.plan(
            {"include_thing": False}, {"include_thing": True}, paths=["gated.py"]
        )
        result = engine.apply(plans)
        assert "unconditional.py" not in result.created
        assert not (engine.project_path / "unconditional.py").exists()


class TestClassification:
    def test_gate_off_to_on_is_create(self, engine: RenderDiffEngine) -> None:
        plan = _plan_for(
            engine,
            {"include_thing": False},
            {"include_thing": True},
            "gated.py",
        )
        assert plan.action == FileAction.CREATE

    def test_gate_off_to_on_overwrites_an_empty_stub_on_disk(
        self, engine: RenderDiffEngine
    ) -> None:
        """A whole-file gate that rendered empty leaves a stub on disk at
        init (``{%- if -%}`` still emits a newline). Flipping the gate on
        must populate that stub, not treat it as a hand-edited file.

        The empty BASE render is what the stub *should* be, so the stub is
        pristine and safe to overwrite. Comparing it against OURS instead
        — which of course differs — misreads it as user content and
        preserves it, leaving the file permanently empty. Non-``.py``
        files make that unrecoverable: ``sweep_empty_stubs`` only sweeps
        ``*.py``, so nothing else cleans it up either.
        """
        (engine.project_path / "gated.py").write_text("\n")

        plan = _plan_for(
            engine,
            {"include_thing": False},
            {"include_thing": True},
            "gated.py",
        )

        assert plan.action in (FileAction.CREATE, FileAction.OVERWRITE), (
            f"empty stub was {plan.action}, so the file stays empty forever"
        )
        assert plan.content is not None and "def handler" in plan.content

    def test_gate_off_to_on_preserves_a_file_with_real_content(
        self, engine: RenderDiffEngine
    ) -> None:
        """The other half: a file with genuine content and no merge base
        (BASE renders empty) still can't be safely reconciled, so it is
        preserved — the issue #773 precedent."""
        (engine.project_path / "gated.py").write_text(
            "def handler() -> None:\n    my_own_implementation()\n"
        )

        plan = _plan_for(
            engine,
            {"include_thing": False},
            {"include_thing": True},
            "gated.py",
        )
        assert plan.action == FileAction.PRESERVE

    def test_gate_on_to_off_pristine_is_delete(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "gated.py").write_text(
            engine._render("gated.py", {"include_thing": True})
        )
        plan = _plan_for(
            engine,
            {"include_thing": True},
            {"include_thing": False},
            "gated.py",
        )
        assert plan.action == FileAction.DELETE

    def test_gate_on_to_off_diverged_is_preserved(
        self, engine: RenderDiffEngine
    ) -> None:
        (engine.project_path / "gated.py").write_text(
            "def handler() -> None:\n    do_something_custom()\n"
        )
        plan = _plan_for(
            engine,
            {"include_thing": True},
            {"include_thing": False},
            "gated.py",
        )
        assert plan.action == FileAction.PRESERVE

    def test_untouched_file_is_skipped(self, engine: RenderDiffEngine) -> None:
        content = engine._render("unconditional.py", {})
        (engine.project_path / "unconditional.py").write_text(content)
        plan = _plan_for(
            engine,
            {"include_thing": False},
            {"include_thing": True},
            "unconditional.py",
        )
        assert plan.action == FileAction.SKIP

    def test_missing_untouched_file_backfills_as_create(
        self, engine: RenderDiffEngine
    ) -> None:
        """BASE == OURS but absent on disk: an older project that predates
        this template file gains it (mirrors the update-path backfill)."""
        plan = _plan_for(
            engine,
            {"include_thing": False},
            {"include_thing": True},
            "unconditional.py",
        )
        assert plan.action == FileAction.CREATE

    def test_pristine_file_is_overwritten(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "plain.py").write_text(
            engine._render("plain.py", {"label": "old"})
        )
        plan = _plan_for(engine, {"label": "old"}, {"label": "new"}, "plain.py")
        assert plan.action == FileAction.OVERWRITE

    def test_diverged_non_overlapping_edit_merges_cleanly(
        self, engine: RenderDiffEngine
    ) -> None:
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
        plan = _plan_for(engine, {"label": "old"}, {"label": "new"}, "plain.py")
        assert plan.action == FileAction.MERGE
        assert plan.conflict is False
        assert plan.content is not None
        assert '"""User docstring."""' in plan.content
        assert '"new"' in plan.content

    def test_diverged_overlapping_edit_conflicts(
        self, engine: RenderDiffEngine
    ) -> None:
        (engine.project_path / "plain.py").write_text(
            "def before() -> None:\n"
            "    pass\n"
            "\n"
            "\n"
            "def value() -> str:\n"
            '    return "mine"\n'
            "\n"
            "\n"
            "def after() -> None:\n"
            "    pass\n"
        )
        plan = _plan_for(engine, {"label": "old"}, {"label": "new"}, "plain.py")
        assert plan.action == FileAction.MERGE
        assert plan.conflict is True
        assert plan.content is not None
        assert "<<<<<<<" in plan.content


class TestVerbatimFiles:
    def test_non_jinja_file_never_templated(self, engine: RenderDiffEngine) -> None:
        content = engine._render("always.txt", {})
        assert content == 'print("{{ not_a_jinja_var }}")\n'


class TestApply:
    def test_apply_writes_created_file(self, engine: RenderDiffEngine) -> None:
        plans = engine.plan({"include_thing": False}, {"include_thing": True})
        result = engine.apply(plans)

        assert "gated.py" in result.created
        assert (engine.project_path / "gated.py").exists()

    def test_apply_deletes_pristine_removed_file(
        self, engine: RenderDiffEngine
    ) -> None:
        (engine.project_path / "gated.py").write_text(
            engine._render("gated.py", {"include_thing": True})
        )
        plans = engine.plan({"include_thing": True}, {"include_thing": False})
        result = engine.apply(plans)

        assert "gated.py" in result.deleted
        assert not (engine.project_path / "gated.py").exists()

    def test_apply_backs_up_before_overwrite(self, engine: RenderDiffEngine) -> None:
        (engine.project_path / "plain.py").write_text(
            engine._render("plain.py", {"label": "old"})
        )
        plans = engine.plan({"label": "old"}, {"label": "new"})
        result = engine.apply(plans, backup=True)

        assert "plain.py" in result.overwritten
        assert "plain.py" in result.backed_up
        assert (engine.project_path / "plain.py.backup").exists()

    def test_apply_reports_preserved_diverged_delete(
        self, engine: RenderDiffEngine
    ) -> None:
        (engine.project_path / "gated.py").write_text(
            "def handler() -> None:\n    do_something_custom()\n"
        )
        plans = engine.plan({"include_thing": True}, {"include_thing": False})
        result = engine.apply(plans)

        assert "gated.py" in result.preserved
        assert (engine.project_path / "gated.py").exists()


class TestPythonFormattingParity:
    def test_created_python_file_is_ruff_formatted(
        self, engine: RenderDiffEngine
    ) -> None:
        if ruff_executable() is None:
            pytest.skip("ruff not available")
        # Single-quoted, template-default formatting -> ruff format should
        # normalize to double quotes the same way `make fix` would at init.
        messy = engine.template_root / PROJECT_SLUG / "messy.py.jinja"
        messy.parent.mkdir(parents=True, exist_ok=True)
        messy.write_text("VALUE = 'hi'\n")

        plans = engine.plan({}, {})
        plan = next(p for p in plans if p.rel_path == "messy.py")
        result = engine.apply([plan])

        assert "messy.py" in result.created
        written = (engine.project_path / "messy.py").read_text()
        assert 'VALUE = "hi"' in written
