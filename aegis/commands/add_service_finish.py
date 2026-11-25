"""``aegis add-service --finish``: the schema of an add that stopped on
conflicts, written once they are resolved."""

from pathlib import Path

import typer

from ..cli import brand
from ..constants import Messages
from ..core import project_deps
from ..core.copier_updater import cleanup_backup_tag, pending_path
from ..core.manual_updater import FINISH_ADD, PENDING_ADD, ManualUpdater
from ..i18n import t
from .update import installed_before, load_pending, refuse_while_conflicted


def finish_add(target_path: Path) -> None:
    """Write and apply the pending add's migrations; refused while a
    conflict remains. A failed migration keeps the record and the backup
    point, so it can be finished again."""
    pending = load_pending(target_path, PENDING_ADD)
    if pending is None:
        brand.error(t("add_service.finish_nothing"), err=True)
        raise typer.Exit(1)
    refuse_while_conflicted(target_path, FINISH_ADD)

    if not ManualUpdater(target_path).write_schema(pending["services"]):
        brand.warn(t("add_service.migration_failed"))
        raise typer.Exit(1)
    pending_path(target_path, PENDING_ADD).unlink()
    if pending.get("backup_tag"):
        cleanup_backup_tag(target_path, pending["backup_tag"])
    brand.success(f"\n{t('add_service.success')}")
    Messages.print_next_steps(
        rebuild=project_deps.dependencies(target_path) != installed_before(pending)
    )
