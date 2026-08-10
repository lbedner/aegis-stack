"""Every stack-dependent file must be accounted for by some mechanism.

Successor to ``tests/cli/test_shared_files_completeness.py``, which asked
"is this hand-maintained list complete?" — a question that stops meaning
anything once the list is gone (RD-07, aegis-stack#922). The underlying
risk it guarded is still real, so it is re-asked against the derivation:

    a file whose content varies with the stack must be handled by
    *something* — the render-diff engine, a component's FileManifest, or
    a deliberate exclusion — and never fall through all three.

Falling through is the #814 failure mode: the file ships stale content in
every existing project after a stack change, silently.

Most of the answer is now derived rather than declared, so most of this
is self-maintaining. The one hand-maintained input left is
``_ENGINE_UNSAFE_PATHS`` — ten paths the engine must not touch because
some other mechanism owns their existence — and that is exactly what
these tests scrutinize: a wrong entry there is now the only way to
silently drop a file.
"""

from __future__ import annotations

import pytest

from aegis.constants import AnswerKeys
from aegis.core.component_files import (
    _ENGINE_UNSAFE_PATHS,
    get_all_owned_paths,
    get_shared_scope,
    get_template_path,
    load_copier_config,
)
from aegis.core.components import COMPONENTS, ComponentType
from aegis.core.render_diff import RenderDiffEngine, build_template_env
from aegis.core.services import SERVICES


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> RenderDiffEngine:
    """``tmp_path_factory`` rather than ``mkdtemp`` so pytest cleans up —
    these tests only render and classify, never ``apply``, so the project
    dir stays empty, but a leaked dir per run adds up in CI.
    """
    template_root = get_template_path()
    return RenderDiffEngine(
        jinja_env=build_template_env(template_root),
        template_root=template_root,
        project_path=tmp_path_factory.mktemp("shared-scope-completeness"),
    )


def _answers(**overrides: object) -> dict[str, object]:
    config = load_copier_config()
    defaults = {
        key: value.get("default")
        for key, value in config.items()
        if isinstance(value, dict) and "default" in value
    }
    return {
        **defaults,
        "project_slug": "demo",
        "project_name": "demo",
        "project_description": "d",
        "author_name": "a",
        **overrides,
    }


def _render_survey(engine: RenderDiffEngine) -> tuple[set[str], set[str]]:
    """Render every discovered path at a minimal and a maximal stack.

    Returns ``(stack_dependent, unrenderable)``. A path is unrenderable
    when a bare Jinja render can't produce it at all — today only
    ``.copier-answers.yml``, which needs Copier's own ``_copier_conf``
    runtime context. Those are returned rather than swallowed so a caller
    can assert they're all deliberately excluded; silently skipping them
    would hide a template that becomes unrenderable by accident.
    """
    minimal = _answers()
    maximal = _answers(
        database_engine="postgres",
        scheduler_backend="postgres",
        worker_backend="arq",
        auth_level="org",
        ai_backend="sqlite",
        **{
            AnswerKeys.include_key(name): True
            for name in (
                *(n for n, s in COMPONENTS.items() if s.type != ComponentType.CORE),
                *SERVICES,
            )
        },
    )

    stack_dependent: set[str] = set()
    unrenderable: set[str] = set()
    for rel_path in engine.discover_paths():
        try:
            differs = engine._render(rel_path, minimal) != engine._render(
                rel_path, maximal
            )
        except Exception:  # noqa: BLE001 - classified by the caller's assertion
            unrenderable.add(rel_path)
            continue
        if differs:
            stack_dependent.add(rel_path)
    return stack_dependent, unrenderable


@pytest.fixture(scope="module")
def survey(engine: RenderDiffEngine) -> tuple[set[str], set[str]]:
    return _render_survey(engine)


@pytest.fixture(scope="module")
def stack_dependent_paths(survey: tuple[set[str], set[str]]) -> set[str]:
    """Paths whose rendered content differs between a minimal and a
    maximal stack — the same signal the old completeness guard used, just
    computed by rendering instead of by generating two real projects."""
    return survey[0]


class TestNothingFallsThroughEveryMechanism:
    def test_every_stack_dependent_file_is_handled(
        self, engine: RenderDiffEngine, stack_dependent_paths: set[str]
    ) -> None:
        scope = set(get_shared_scope(engine.discover_paths()))
        owned = get_all_owned_paths()

        unhandled = stack_dependent_paths - scope - owned - _ENGINE_UNSAFE_PATHS
        assert not unhandled, (
            "These files render differently across stacks but are handled by "
            "nothing — not the render-diff engine, not a component's "
            "FileManifest, and not a deliberate exclusion. They will ship "
            "stale content after a stack change:\n  - "
            + "\n  - ".join(sorted(unhandled))
        )

    def test_exclusions_are_the_only_hand_maintained_input(
        self, engine: RenderDiffEngine, stack_dependent_paths: set[str]
    ) -> None:
        """Everything stack-dependent that the engine does NOT handle must
        be explained by ownership or by an explicit exclusion — never by
        accident. Pins how much is still declared by hand, so growth in
        that number is a deliberate, visible choice.
        """
        scope = set(get_shared_scope(engine.discover_paths()))
        owned = get_all_owned_paths()

        excluded_and_stack_dependent = stack_dependent_paths & _ENGINE_UNSAFE_PATHS
        unexplained = (stack_dependent_paths - scope) - owned
        assert unexplained == excluded_and_stack_dependent, (
            "the set of stack-dependent files the engine skips no longer "
            "matches the deliberate exclusions — something is being dropped "
            f"for an unrecorded reason: {sorted(unexplained - excluded_and_stack_dependent)}"
        )

    def test_unrenderable_templates_are_all_deliberate_exclusions(
        self, survey: tuple[set[str], set[str]]
    ) -> None:
        """A template a bare Jinja render can't produce must be one we
        deliberately keep out of the engine's reach — otherwise the engine
        would crash the whole operation the first time it touched it."""
        _stack_dependent, unrenderable = survey
        assert unrenderable <= _ENGINE_UNSAFE_PATHS, (
            "These templates cannot be rendered outside Copier but are not "
            "excluded from the engine's scope — the engine will raise on "
            f"them: {sorted(unrenderable - _ENGINE_UNSAFE_PATHS)}"
        )


class TestExclusionsStayHonest:
    """The old guard's ``test_allowlist_has_no_stale_entries``, re-aimed at
    the list that actually survives."""

    def test_the_exclusion_set_is_exactly_this(self) -> None:
        """Pinned deliberately.

        Every other check here treats "it's excluded" as sufficient
        justification — which means *adding* a path to
        ``_ENGINE_UNSAFE_PATHS`` makes the file vanish from the engine's
        reach without any test complaining. That is the one remaining way
        to silently drop a shared file, so the set itself is pinned:
        changing it requires editing this test, which puts the change in
        front of a reviewer alongside the reason recorded in
        ``component_files.py``'s comment block.

        Verified: without this, adding ``docker-compose.yml`` to the
        exclusions passes every other assertion in this file.
        """
        assert (
            frozenset(
                {
                    # Copier's own bookkeeping; needs `_copier_conf` to render.
                    ".copier-answers.yml",
                    # Cross-cutting; owned by the migration bootstrap.
                    "alembic/alembic.ini",
                    "alembic/env.py",
                    "alembic/script.py.mako",
                    "alembic/versions/.gitkeep",
                    # Regenerated at runtime by `make serve`.
                    ".env.ports",
                    # Restored by ManualUpdater's cross-spec ensure-hooks.
                    "app/components/frontend/dashboard/cards/services_card.py",
                    ".claude/skills/add-model-and-migration/SKILL.md",
                    # Post-gen aggregate conditions, no restoration hook —
                    # excluded to match the pre-engine behavior exactly.
                    "docs/components/api-load-testing.md",
                    "tests/services/test_health_logic.py",
                }
            )
            == _ENGINE_UNSAFE_PATHS
        ), (
            "_ENGINE_UNSAFE_PATHS changed. Adding an entry removes a file "
            "from the render-diff engine's reach — confirm some other "
            "mechanism genuinely owns it, record why in component_files.py, "
            "then update this test."
        )

    def test_every_exclusion_still_exists_in_the_template_tree(
        self, engine: RenderDiffEngine
    ) -> None:
        discovered = set(engine.discover_paths())
        stale = _ENGINE_UNSAFE_PATHS - discovered
        assert not stale, (
            "These paths are excluded from the engine but no longer ship in "
            "the template tree at all — drop them from _ENGINE_UNSAFE_PATHS:\n  - "
            + "\n  - ".join(sorted(stale))
        )

    def test_no_exclusion_is_also_manifest_owned(self) -> None:
        """An owned path is already out of scope by derivation; excluding
        it too is redundant and hides which mechanism actually governs it."""
        redundant = _ENGINE_UNSAFE_PATHS & get_all_owned_paths()
        assert not redundant, (
            "These paths are both manifest-owned and explicitly excluded — "
            "the exclusion is redundant, drop it:\n  - "
            + "\n  - ".join(sorted(redundant))
        )
