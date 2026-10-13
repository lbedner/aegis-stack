"""Overseer > Deployments: where it runs (the provider, ``hosting``),
what is live (build, commit, when it went live, health), the
host it runs on, and the database backups beside it, from
``ui_deployments``; the deploy history joins it with deploy records. Its
actions (a new server, deploy, back up, roll back, destroy) are
``overseer_deploy_actions``."""

from typing import Any

from app.services.system import hosting, ui_deployments
from app.services.system.models import ComponentStatus

from . import overseer_deploy_actions
from .overseer_nav import NavItem, SectionRequest
from .rendering import columns, status_cell

SECTIONS = (
    (None, {"overview": "Overview", "history": "History", "backups": "Backups"}),
)
ITEM = NavItem(
    group="deployments",
    name="deployments",
    title="Deployments",
    url="/overseer/deployments",
    status="",
    component=ComponentStatus(name="deployments", message=""),
)
BACKUP_COLUMNS = columns(ui_deployments.BACKUP_COLUMNS)
HISTORY_COLUMNS = columns(ui_deployments.HISTORY_COLUMNS, status=("health",))
# A deploy's health check, as a status cell's tone.
HEALTH_TONES = {"passed": "ok", "failed": "error"}


async def section_context(
    section: str, component: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    if section == "history":
        found = await ui_deployments.history()
        rows = [
            r
            | {
                "health": status_cell(
                    r["health"], HEALTH_TONES.get(r["health"], "muted")
                )
                if r["health"]
                else ""
            }
            for r in found["rows"]
        ]
        return {
            "section_subtitle": "Each build that went live, newest first.",
            "history": found | {"rows": rows},
            "history_columns": HISTORY_COLUMNS,
        }
    if section == "backups":
        return {
            "section_subtitle": "The scheduled database backups, newest first.",
            "backups": ui_deployments.backups(),
            "backup_columns": BACKUP_COLUMNS,
        }
    return {
        "section_subtitle": "What is live, where it runs, and how to put it on a server.",
        "running": await hosting.running_on(),
        "now": await ui_deployments.now(),
        "host": await ui_deployments.host(),
        "actions": await overseer_deploy_actions.context(),
    }
