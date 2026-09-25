"""Adding a service re-renders what other installed specs own and branch on.

A file a spec owns is copied once, when that spec is added, and never
rendered again - so a template that branches on ANOTHER service's flag kept
its first render forever. ``add-service auth`` onto a finance project left
``finance/models/base.py`` at ``_OWNER_FK = None`` (no owner keys, #1217),
and the scheduler, worker, blog, comms, insights and AI routers without the
auth guards they render once auth exists.

``get_cross_spec_scope`` puts the other specs' owned files that are on disk
in front of the render-diff engine, which renders each before and after the
change and touches only the ones whose output moves.
"""

from __future__ import annotations

from collections.abc import Callable

from aegis.core.component_files import (
    OWNED_BUT_SHARED_PATHS,
    get_component_files,
    get_cross_spec_scope,
)

FINANCE_MODELS = "app/services/finance/models/base.py"
SCHEDULER_API = "app/components/backend/api/scheduler.py"
TEMPLATE_PATHS = [
    FINANCE_MODELS,
    SCHEDULER_API,
    "app/components/scheduler/main.py",
    "app/services/auth/service.py",
    ".copier-answers.yml",
    "app/core/config.py",
]


def _on_disk(*present: str) -> Callable[[str], bool]:
    return lambda rel: rel in present


def test_other_specs_files_on_disk_are_in_scope() -> None:
    scope = get_cross_spec_scope(
        TEMPLATE_PATHS, _on_disk(FINANCE_MODELS, SCHEDULER_API), operated="auth"
    )

    assert FINANCE_MODELS in scope
    assert SCHEDULER_API in scope


def test_a_file_not_on_disk_is_never_created() -> None:
    """Existence stays manifest-owned: a spec that is not installed does not
    get its files backfilled by an unrelated add."""
    scope = get_cross_spec_scope(TEMPLATE_PATHS, _on_disk(), operated="auth")

    assert FINANCE_MODELS not in scope


def test_the_spec_being_added_is_left_to_its_own_copy() -> None:
    auth_files = set(get_component_files("auth", full=True))
    auth_file = next(p for p in TEMPLATE_PATHS if p in auth_files)

    scope = get_cross_spec_scope(
        TEMPLATE_PATHS, _on_disk(auth_file, FINANCE_MODELS), operated="auth"
    )

    assert auth_file not in scope


def test_unowned_and_unsafe_paths_stay_out() -> None:
    """Unowned files are the shared scope's job; Copier's own answers file
    is never the engine's."""
    scope = get_cross_spec_scope(
        TEMPLATE_PATHS,
        _on_disk(".copier-answers.yml", "app/core/config.py"),
        operated="auth",
    )

    assert ".copier-answers.yml" not in scope
    assert "app/core/config.py" not in scope


def test_the_old_single_exception_is_covered_by_the_rule() -> None:
    """``scheduler/main.py`` was hand-listed for exactly this reason."""
    scope = get_cross_spec_scope(
        TEMPLATE_PATHS, _on_disk(*OWNED_BUT_SHARED_PATHS), operated="insights"
    )

    assert set(OWNED_BUT_SHARED_PATHS) <= set(scope)
