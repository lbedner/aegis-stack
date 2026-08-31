"""Spec-declared post-render hooks (RD-06, aegis-stack#921).

Almost everything a component contributes is declarative: files it owns
(``FileManifest``), wiring it injects (``PluginWiring``), options it
accepts (``OptionSpec``). One thing isn't — a *transform* applied to
files after they land.

The worker component is the case that forced this. Its templates ship
every backend's implementation side by side (``pools_arq.py``,
``pools_dramatiq.py``, ``pools_taskiq.py``); picking a backend means
renaming the chosen one onto the canonical ``pools.py`` and deleting the
others. That is not expressible as a file list or a render diff — it is
a rename, and the render-diff engine has no vocabulary for renames.

Before this, that transform was a hardcoded ``if component ==
ComponentNames.WORKER`` branch inside ``ManualUpdater.add_component``,
mirrored by a second hardcoded branch in ``post_gen_tasks``. A
third-party plugin needing the same shape had no way to ask for it.

``PluginSpec.post_render`` is the escape hatch: a callable the spec
declares, invoked with ``(project_path, answers)`` once the component's
files are on disk. Hooks for the genuinely weird cases; declarative data
for everything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis.core.components import COMPONENTS
from aegis.core.file_manifest import FileManifest
from aegis.core.plugins.spec import PluginKind, PluginSpec


class TestSpecDeclaresPostRender:
    def test_defaults_to_none(self) -> None:
        """A spec that declares no hook has none — the overwhelming
        majority, and the path that must stay zero-cost."""
        spec = PluginSpec(
            name="hookless",
            kind=PluginKind.SERVICE,
            description="No post-render transform.",
            files=FileManifest(),
        )
        assert spec.post_render is None

    def test_accepts_a_callable(self) -> None:
        calls: list[tuple[Path, dict[str, Any]]] = []

        def hook(project_path: Path, answers: dict[str, Any]) -> None:
            calls.append((project_path, answers))

        spec = PluginSpec(
            name="hooked",
            kind=PluginKind.SERVICE,
            description="Has a post-render transform.",
            files=FileManifest(),
            post_render=hook,
        )
        assert spec.post_render is hook

        spec.post_render(Path("/tmp/demo"), {"include_hooked": True})
        assert calls == [(Path("/tmp/demo"), {"include_hooked": True})]


class TestWorkerDeclaresItsPatternDTransform:
    """The worker component's backend rename must be declared on its
    spec, not hardcoded in the updater."""

    def test_worker_spec_has_a_post_render_hook(self) -> None:
        assert COMPONENTS["worker"].post_render is not None, (
            "worker's Pattern D backend rename is still hardcoded somewhere "
            "instead of declared on its spec"
        )

    @staticmethod
    def _worker_tree(root: Path) -> Path:
        """A worker install shaped the way the templates render it.

        ``queues/`` matters: ``cleanup_worker_backend_files`` treats its
        absence as "no worker here" and returns early, so a fixture
        without it silently exercises nothing.
        """
        worker_dir = root / "app/components/worker"
        (worker_dir / "queues").mkdir(parents=True)
        (worker_dir / "queues" / "__init__.py").write_text("")
        (worker_dir / "queues" / "system.py").write_text("# arq queue\n")
        (worker_dir / "queues" / "system_dramatiq.py").write_text("# dramatiq queue\n")
        (worker_dir / "pools.py").write_text("# arq\n")
        (worker_dir / "pools_dramatiq.py").write_text("# dramatiq\n")
        (worker_dir / "pools_taskiq.py").write_text("# taskiq\n")
        return worker_dir

    def test_hook_renames_chosen_backend_onto_canonical_names(
        self, tmp_path: Path
    ) -> None:
        """Calling the declared hook directly performs the rename — the
        behavior ``cleanup_worker_backend_files`` provides, now reachable
        generically through the spec."""
        worker_dir = self._worker_tree(tmp_path)

        hook = COMPONENTS["worker"].post_render
        assert hook is not None
        hook(tmp_path, {"worker_backend": "dramatiq"})

        assert (worker_dir / "pools.py").read_text() == "# dramatiq\n"
        assert not (worker_dir / "pools_dramatiq.py").exists()
        assert not (worker_dir / "pools_taskiq.py").exists()
        # The queue variant is resolved onto its canonical name too.
        assert (worker_dir / "queues" / "system.py").read_text() == "# dramatiq queue\n"
        assert not (worker_dir / "queues" / "system_dramatiq.py").exists()

    def test_hook_strips_other_backends_for_the_default(self, tmp_path: Path) -> None:
        """arq ships at the canonical names already; the hook leaves them
        alone and only strips the other backends' siblings."""
        worker_dir = self._worker_tree(tmp_path)

        hook = COMPONENTS["worker"].post_render
        assert hook is not None
        hook(tmp_path, {"worker_backend": "arq"})

        assert (worker_dir / "pools.py").read_text() == "# arq\n"
        assert not (worker_dir / "pools_dramatiq.py").exists()
        assert not (worker_dir / "pools_taskiq.py").exists()


class TestSpecDeclaresAnswerResets:
    """Removing a component should revert the answer keys that only mean
    something while it is installed — scheduler's backend choice being
    the in-tree case. Declared on the spec rather than branched on by
    name in ``remove_component``."""

    def test_scheduler_declares_its_resets(self) -> None:
        assert COMPONENTS["scheduler"].reset_answers_on_remove == {
            "scheduler_backend": "memory",
            "scheduler_with_persistence": False,
        }

    def test_most_specs_declare_none(self) -> None:
        assert COMPONENTS["redis"].reset_answers_on_remove == {}

    def test_remove_applies_the_declared_resets(self, tmp_path: Path) -> None:
        """The behavior the hardcoded branch used to provide, now driven
        by the declaration."""
        from aegis.core.manual_updater import ManualUpdater

        project = tmp_path / "demo-project"
        project.mkdir()
        (project / ".copier-answers.yml").write_text(
            "# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY\n"
            "project_name: Demo\n"
            "project_slug: demo-project\n"
            "include_scheduler: true\n"
            "scheduler_backend: postgres\n"
            "scheduler_with_persistence: true\n"
            "_commit: None\n"
            "_src_path: aegis/templates/copier-aegis-project\n"
        )
        updater = ManualUpdater(project)
        answers = updater._apply_removal_answer_resets(
            "scheduler", {**updater.answers, "include_scheduler": False}
        )

        assert answers["scheduler_backend"] == "memory"
        assert answers["scheduler_with_persistence"] is False

    def test_reset_is_a_no_op_for_specs_without_one(self, tmp_path: Path) -> None:
        from aegis.core.manual_updater import ManualUpdater

        project = tmp_path / "demo-project"
        project.mkdir()
        (project / ".copier-answers.yml").write_text(
            "# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY\n"
            "project_name: Demo\n"
            "project_slug: demo-project\n"
            "include_redis: true\n"
            "_commit: None\n"
            "_src_path: aegis/templates/copier-aegis-project\n"
        )
        updater = ManualUpdater(project)
        before = {**updater.answers, "include_redis": False}
        after = updater._apply_removal_answer_resets("redis", dict(before))

        assert after == before


class TestNoComponentNameSpecialCasesRemain:
    """RD-06's acceptance criterion, enforced as a test rather than a
    review note: the updater must not branch on specific component names
    to decide what to do to a project.

    One documented exception remains — see
    ``test_remaining_special_case_is_the_documented_one``.
    """

    def test_manual_updater_has_no_worker_special_case(self) -> None:
        source = Path("aegis/core/manual_updater.py").read_text()
        assert "ComponentNames.WORKER" not in source, (
            "ManualUpdater still branches on the worker component by name; "
            "the Pattern D transform belongs on the spec's post_render hook"
        )

    def test_manual_updater_has_no_scheduler_removal_special_case(self) -> None:
        """The answer-reset branch is now a spec declaration."""
        source = Path("aegis/core/manual_updater.py").read_text()
        assert "SCHEDULER_WITH_PERSISTENCE" not in source, (
            "ManualUpdater still hardcodes scheduler's removal answer reset; "
            "it belongs in the spec's reset_answers_on_remove"
        )

    def test_remaining_special_case_is_the_documented_one(self) -> None:
        """Exactly one ``ComponentNames.SCHEDULER`` branch is left in
        ManualUpdater: the ``backend_variant`` argument threaded into
        ``get_component_files``.

        Deliberately not generalized. Unlike the additive ``extras``
        groups, scheduler persistence needs *subtractive* semantics
        (persistence paths are reachable through ``primary``, and on the
        memory backend they render as 0-byte stubs that must be removed
        from the add base, not merely not-added). Expressing that means
        giving ``FileManifest`` predicate-gated *and* subtractive extras
        — a change to the hot path shared by init, add, remove, and the
        ownership derivation, for no behavioral gain.

        It is also entangled with a genuine pre-existing bug: the
        obvious collapse target, ``scheduler_with_persistence``, is
        computed inconsistently across paths (``!= memory`` at init,
        ``== sqlite`` on add), so folding file selection onto it would
        propagate that divergence into which files get written.

        This test pins the count so the exception can't quietly grow.
        """
        source = Path("aegis/core/manual_updater.py").read_text()
        assert source.count("ComponentNames.SCHEDULER") == 1, (
            "the number of scheduler special cases in ManualUpdater changed — "
            "if one was added, generalize it instead; if the remaining one was "
            "removed, delete this test"
        )
