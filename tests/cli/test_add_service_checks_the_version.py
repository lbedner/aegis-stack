"""``add-service`` runs against a project it may not be able to generate.

``add``, ``remove`` and ``remove-service`` all call
``validate_version_compatibility`` before touching anything.
``add-service`` did not, and it is the one that writes the most.

What that cost, on a 0.11.0 project with a 0.12.1 CLI (2026-09-20): the
run installed 53 files including today's ``app/cli/migrate_gen.py``,
left the project's own 0.11.0 ``alembic/env.py`` alone - it has nothing
to do with auth - and so produced a project whose generator sets
``render_as_batch`` through a contract its ``env.py`` cannot hear. Then
every migration failed, four different ways, and the project was left
with the service's code and none of its schema.

The check already blocks on a minor-version difference unless
``--force``. One line, and none of that happens.
"""

from __future__ import annotations

import inspect

from aegis.commands import add_service


def test_it_validates_before_writing_anything() -> None:
    source = inspect.getsource(add_service)
    assert "validate_version_compatibility" in source, (
        "add-service writes more than any other command and is the only "
        "one of the four that never checks the project's template version"
    )


def test_the_check_comes_before_the_work() -> None:
    """A check after the first file is written is not a check."""
    source = inspect.getsource(add_service)
    checked = source.index("validate_version_compatibility(")
    # ManualUpdater is what puts files on disk.
    wrote = source.index("ManualUpdater(target_path)")
    assert checked < wrote, "the version is checked after files are written"


def test_force_is_offered_so_the_check_can_be_overridden() -> None:
    """Its siblings all take ``--force``; a block with no way past it
    would make a deliberate cross-version add impossible."""
    assert "force" in inspect.signature(add_service.add_service_command).parameters
