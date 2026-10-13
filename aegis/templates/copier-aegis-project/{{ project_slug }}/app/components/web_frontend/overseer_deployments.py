"""Overseer > Deployments. Its Overview is what is deployed: where this
build runs (the provider, ``hosting``; the live build, commit, health and
host, ``ui_deployments``), the server it deploys to and what can be done
to it, and every connected cloud account's servers. New server is the way
to one, step by step; History joins deploys with their records; Backups
the database's. The actions (a new server, deploy, back up, roll back,
destroy) are ``overseer_deploy_actions``."""

from typing import Any

from app.core import secrets
from app.services.system import hosting, ui_deployments
from app.services.system.models import ComponentStatus

from . import overseer_deploy_actions as actions
from . import overseer_secrets
from .overseer_nav import NavItem, SectionRequest
from .rendering import columns, status_cell

SECTIONS = (
    (
        None,
        {
            "overview": "Overview",
            "new": "New server",
            "history": "History",
            "backups": "Backups",
        },
    ),
)
ITEM = NavItem(
    group="deployments",
    name="deployments",
    title="Deployments",
    url="/overseer/deployments",
    status="",
    component=ComponentStatus(name="deployments", message=""),
)
NEW_URL = f"{ITEM.url}/new"
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
    if section == "new":
        return {
            "section_subtitle": "From this machine to a server of its own.",
            "actions": await _steps_context(),
            "overview_url": ITEM.url,
        }
    return {
        "section_subtitle": "What is deployed, and where.",
        "running": await hosting.running_on(),
        "now": await ui_deployments.now(),
        "host": await ui_deployments.host(),
        "actions": await _deployed(),
        "new_url": NEW_URL,
    }


async def _deployed() -> dict[str, Any]:
    """The Overview's card: a deployed server (redeploys come from
    elsewhere), the server this project deploys to and what can be done to
    it, or none yet; with every connected cloud account's servers."""
    if actions.deployed():
        return actions.DEPLOYED_VIEW
    found = await actions.shared()
    found["accounts"] = await actions.accounts(found["agent"])
    if not hosting.deploy_config().get("server"):
        return found | {"view": "no-server"}
    return found | {
        "view": "server",
        "server": hosting.deploys_to(),
        "destroy": actions.server_name(),
    }


# The way from this machine to a server, in order. Provisioning deploys,
# so the server step ends with the app live there. A domain of your own is
# optional: without one the server gets an sslip.io name.
STEPS = (
    ("agent", "Deploy agent"),
    ("where", "Where"),
    ("domain", "Domain"),
    ("server", "Server"),
)
OPTIONAL = {"domain"}
OWN_SERVER = "aegis deploy-init --host <your server's address>"


def _secrets_page() -> str | None:
    """Where a token can be set from here: the Secrets page, with the
    secrets component to keep it; None where only ``.env`` can."""
    return overseer_secrets.url() if overseer_secrets.has_component() else None


def _steps(summaries: dict[str, str]) -> list[dict[str, Any]]:
    """``STEPS``, each done (it has a summary), the one at hand (the first
    not done), still to come, or, not done but ``OPTIONAL``, open without
    holding up the next."""
    found = []
    for key, title in STEPS:
        status = "done" if key in summaries else "todo"
        if status == "todo" and key in OPTIONAL:
            status = "optional"
        elif status == "todo" and all(
            s["status"] in ("done", "optional") for s in found
        ):
            status = "current"
        found.append(
            {
                "key": key,
                "title": title,
                "status": status,
                "summary": summaries.get(key),
            }
        )
    return found


async def _dns(back: str) -> list[dict[str, Any]]:
    """Each DNS provider and its keys: whether the app holds each (Overseer
    > Secrets, or ``.env``), and the dialog that sets it, which comes back
    to ``back``."""
    names = [name for p in hosting.DNS for name in p.secrets]
    found = await secrets.get_many(*names)
    return [
        {
            "key": p.key,
            "name": p.name,
            "logo": p.logo,
            "secrets": [
                {
                    "name": name,
                    "held": bool(found.get(name)),
                    "url": overseer_secrets.set_url(name, back),
                }
                for name in p.secrets
            ],
        }
        for p in hosting.DNS
    ]


async def _steps_context() -> dict[str, Any]:
    """The steps to a new server, each read from what is true; on a deployed
    server, or with a server already, where to go instead."""
    if actions.deployed():
        return actions.DEPLOYED_VIEW
    found = await actions.shared()
    if hosting.deploy_config().get("server"):
        return found | {"view": "has-server", "server": hosting.deploys_to()}
    agent = found["agent"]
    listening = agent["state"] == "ready"
    held = await actions.held(agent.get("beat") or {})
    providers = [p for p in hosting.PROVISIONABLE if p.key in held]
    summaries = {}
    if listening:
        beat = agent["beat"]
        summaries["agent"] = f"Listening on {beat['host']} (aegis {beat['version']})"
    if providers:
        summaries["where"] = ", ".join(p.name for p in providers) + ": token set"
    dns = await _dns(NEW_URL)
    if named := [d["name"] for d in dns if all(k["held"] for k in d["secrets"])]:
        summaries["domain"] = ", ".join(named) + ": keys set"
    return found | {
        "view": "steps",
        "steps": _steps(summaries),
        "dns": dns,
        "providers": [actions.waiting(p) for p in providers] if listening else [],
        "missing": [
            {"key": p.key, "name": p.name, "token": p.token}
            for p in hosting.PROVISIONABLE
            if p.key not in held
        ],
        "secrets_page": _secrets_page(),
        "own_server": OWN_SERVER,
        "terminal": [
            {"name": p.name, "command": p.command, "token": p.token}
            for p in hosting.PROVIDERS
        ],
    }
