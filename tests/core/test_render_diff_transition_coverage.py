"""Every add/remove transition must actually write the files it needs.

The guard that would have caught the ingress bug, generalized. That bug
(``aegis add ingress`` silently leaving ``docker-compose.prod.yml``,
``.env.deploy.example`` and ``scripts/server-setup.sh`` empty forever)
survived every regression sweep across two tickets, because no test
covered "add a component whose shared files are whole-file gated". Its
shape was: the engine *classified* the file, decided ``PRESERVE``, and
silently produced nothing — a wrong answer, not a crash.

So rather than assert on specific files, these assert the *property*: for
any transition, every shared file the target configuration needs must end
up written. A future template that adds a gated file to some component is
covered automatically, with no registration anywhere.

This is deliberately a pure-render sweep — no project generation — so it
runs in seconds and can afford to cover every component and service in
both directions. The trade-off is that it simulates the on-disk state
rather than observing a real one; ``tests/cli/test_add_ingress_populates_stubs.py``
is the end-to-end counterpart that proves the simulation is faithful.

Intended to outlive ``tests/cli/test_shared_files_completeness.py``: that
one checks a hand-maintained list is complete, which stops meaning
anything once the list is gone (RD-07, aegis-stack#922). This one checks
the derivation behaves, which keeps meaning something.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.constants import AnswerKeys
from aegis.core.component_files import (
    get_shared_scope,
    get_template_path,
    load_copier_config,
)
from aegis.core.components import COMPONENTS, ComponentType
from aegis.core.render_diff import (
    FileAction,
    FilePlan,
    RenderDiffEngine,
    build_template_env,
)
from aegis.core.services import SERVICES

# Actions that put the target content on disk. Anything else means the
# operation quietly declined to write a file the stack needs.
WRITING_ACTIONS = frozenset({FileAction.CREATE, FileAction.OVERWRITE, FileAction.MERGE})
# Removal may also legitimately delete.
RESOLVING_ACTIONS = WRITING_ACTIONS | {FileAction.DELETE}


def _optional_specs() -> list[str]:
    """Every component/service a project can add or remove."""
    names = [n for n, s in COMPONENTS.items() if s.type != ComponentType.CORE]
    names.extend(SERVICES.keys())
    return names


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> RenderDiffEngine:
    template_root = get_template_path()
    return RenderDiffEngine(
        jinja_env=build_template_env(template_root),
        template_root=template_root,
        project_path=tmp_path_factory.mktemp("transition-coverage"),
    )


@pytest.fixture(scope="module")
def scope(engine: RenderDiffEngine) -> list[str]:
    return get_shared_scope(engine.discover_paths())


@pytest.fixture(scope="module")
def base_answers() -> dict[str, object]:
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
    }


@pytest.fixture(scope="module")
def maximal_answers(base_answers: dict[str, object]) -> dict[str, object]:
    """Everything on, with the variant axes pinned to non-default values
    so option-gated content is exercised too."""
    answers = {
        **base_answers,
        "database_engine": "postgres",
        "scheduler_backend": "postgres",
        "worker_backend": "arq",
        "auth_level": "org",
        "ai_backend": "sqlite",
    }
    for name in _optional_specs():
        answers[AnswerKeys.include_key(name)] = True
    return answers


def _simulate_disk(engine: RenderDiffEngine, rel_path: str, rendered: str) -> Path:
    """Materialize what a real init of ``rendered``'s configuration leaves.

    Faithful in the one respect that matters here: a whole-file gate that
    rendered empty still leaves a 1-byte stub on disk (``{%- if -%}``
    emits a newline and Copier writes the file), and post-gen's
    ``sweep_empty_stubs`` removes those only for ``*.py``. Getting this
    wrong is what let the original bug hide — a sweep that assumed
    "renders empty" meant "absent from disk" would have found nothing.
    """
    path = engine.project_path / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rendered and rel_path.endswith(".py"):
        path.unlink(missing_ok=True)
    else:
        path.write_text(rendered if rendered else "\n")
    return path


def _classify_transition(
    engine: RenderDiffEngine,
    rel_path: str,
    before: dict[str, object],
    after: dict[str, object],
) -> tuple[str, str, FilePlan] | None:
    """Classify one file across one transition, or None if untouched."""
    base = engine._render(rel_path, before)
    ours = engine._render(rel_path, after)
    if base == ours:
        return None
    project_file = _simulate_disk(engine, rel_path, base)
    try:
        plan = engine._classify(
            rel_path, base, ours, project_file, engine.policy_for(rel_path)
        )
    finally:
        project_file.unlink(missing_ok=True)
    return base, ours, plan


class TestEveryAddWritesWhatItNeeds:
    @pytest.mark.parametrize("name", _optional_specs())
    def test_add_to_a_minimal_project(
        self,
        engine: RenderDiffEngine,
        scope: list[str],
        base_answers: dict[str, object],
        name: str,
    ) -> None:
        after = {**base_answers, AnswerKeys.include_key(name): True}

        unwritten: list[str] = []
        for rel_path in scope:
            outcome = _classify_transition(engine, rel_path, base_answers, after)
            if outcome is None:
                continue
            _base, ours, plan = outcome
            if ours and plan.action not in WRITING_ACTIONS:
                unwritten.append(f"{rel_path} -> {plan.action.value}")

        assert not unwritten, (
            f"adding {name!r} leaves shared files it needs unwritten:\n  "
            + "\n  ".join(unwritten)
        )

    @pytest.mark.parametrize("name", _optional_specs())
    def test_add_into_a_full_stack(
        self,
        engine: RenderDiffEngine,
        scope: list[str],
        maximal_answers: dict[str, object],
        name: str,
    ) -> None:
        """Some shared content only changes for X when a *different*
        component is also present, so a minimal-base sweep can't see it."""
        before = {**maximal_answers, AnswerKeys.include_key(name): False}

        unwritten: list[str] = []
        for rel_path in scope:
            outcome = _classify_transition(engine, rel_path, before, maximal_answers)
            if outcome is None:
                continue
            _base, ours, plan = outcome
            if ours and plan.action not in WRITING_ACTIONS:
                unwritten.append(f"{rel_path} -> {plan.action.value}")

        assert not unwritten, (
            f"adding {name!r} to a full stack leaves shared files unwritten:\n  "
            + "\n  ".join(unwritten)
        )


class TestEveryRemoveResolvesWhatItChanges:
    @pytest.mark.parametrize("name", _optional_specs())
    def test_remove_from_a_project_that_has_it(
        self,
        engine: RenderDiffEngine,
        scope: list[str],
        base_answers: dict[str, object],
        name: str,
    ) -> None:
        """The mirror: stale wiring for a component the project no longer
        has is the #814 failure mode, just pointing the other way."""
        before = {**base_answers, AnswerKeys.include_key(name): True}

        unresolved: list[str] = []
        for rel_path in scope:
            outcome = _classify_transition(engine, rel_path, before, base_answers)
            if outcome is None:
                continue
            _base, _ours, plan = outcome
            if plan.action not in RESOLVING_ACTIONS:
                unresolved.append(f"{rel_path} -> {plan.action.value}")

        assert not unresolved, (
            f"removing {name!r} leaves stale shared files behind:\n  "
            + "\n  ".join(unresolved)
        )
