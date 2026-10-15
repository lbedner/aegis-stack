"""Overseer > Deployments. Its Overview is what is deployed: where this
build runs (the provider, ``hosting``; the live build, commit, health and
host, ``ui_deployments``), the server it deploys to and what can be done
to it, and every connected cloud account's servers. New server is the way
to one, step by step; History joins deploys with their records; Backups
the database's. The actions (a new server, deploy, back up, roll back,
destroy) are ``overseer_deploy_actions``."""

from collections.abc import Iterable, Set
from typing import Any

from app.core import exposure, secrets
from app.core.parts import Category
from app.services.system import hosting, ui_deployments
from app.services.system.models import ComponentStatus

from . import overseer_deploy_actions as actions
from . import overseer_deploy_form as deploy_form
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
    concern=Category.STACK,
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
            # Whether a key can be set here (the Secrets rows' actions read it).
            "writable": secrets.writable(),
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
    if exposure.deployed():
        return actions.DEPLOYED_VIEW
    found = await actions.shared()
    found["accounts"] = await deploy_form.accounts(found["agent"])
    if actions.creating(found["job"]):  # New server shows it, step by step
        return found | {"view": "creating"}
    if not hosting.deploy_config().get("server"):
        return found | {"view": "no-server"}
    return found | {
        "view": "server",
        "server": hosting.deploys_to(),
        "destroy": actions.server_name(),
        "rollback": deploy_form.ROLLBACK_WAITING,
    }


# The way from this machine to a server, in order: the agent that runs it,
# a domain of your own (optional: without one the server gets an sslip.io
# name), then the server: its cloud, that cloud's keys, and the server.
# Provisioning deploys, so the server step ends with the app live there.
STEPS = (("agent", "Deploy agent"), ("domain", "Domain"), ("server", "Server"))
OPTIONAL = {"domain"}


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
                # Its body shown: at hand, or optional (its provider can
                # still change once done).
                "open": status == "current" or key in OPTIONAL,
            }
        )
    return found


def _choices(
    providers: Iterable[hosting.Provider],
    rows: dict[str, dict[str, Any]],
    elsewhere: Set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Each of ``providers`` to pick from: its terminal way (``command``,
    and the keys it ``reads``), its keys as Overseer > Secrets shows them
    (``rows``), and whether it is held, by the app, or, for one in
    ``elsewhere``, where the deploy agent runs."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "logo": p.logo,
            "command": p.command,
            "reads": list(p.secrets),
            "elsewhere": p.key in elsewhere,
            "held": p.key in elsewhere or all(rows[n]["held"] for n in p.secrets),
            "secrets": [rows[n] for n in p.secrets],
        }
        for p in providers
    ]


def _opens_on(choices: list[dict[str, Any]], otherwise: str) -> str:
    """The provider a picker opens on: one whose keys are all set, else one
    with some set (saving a key reloads the page, half way through a
    pair), else ``otherwise``."""
    started = [c for c in choices if c["held"] or any(r["held"] for r in c["secrets"])]
    started.sort(key=lambda c: not c["held"])
    return started[0]["key"] if started else otherwise


async def _steps_context() -> dict[str, Any]:
    """The steps to a new server, each read from what is true; on a deployed
    server, or with a server already, where to go instead."""
    if exposure.deployed():
        return actions.DEPLOYED_VIEW
    found = await actions.shared()
    if actions.creating(found["job"]):
        return found | {"view": "creating"}
    if hosting.deploy_config().get("server"):
        return found | {"view": "has-server", "server": hosting.deploys_to()}
    agent = found["agent"]
    listening = agent["state"] == "ready"
    summaries = {}
    if listening:
        beat = agent["beat"]
        summaries["agent"] = f"Listening on {beat['host']} (aegis {beat['version']})"
    # Every key on the page in one read: the clouds' and the DNS providers'.
    names = [n for p in (*hosting.PROVISIONABLE, *hosting.DNS) for n in p.secrets]
    rows = await overseer_secrets.rows_for(names, NEW_URL)
    agents = set((agent.get("beat") or {}).get("providers") or ())
    clouds = _choices(hosting.PROVISIONABLE, rows, agents)
    for cloud, p in zip(clouds, hosting.PROVISIONABLE, strict=True):
        # Its new-server form, where the agent can be asked with its token.
        cloud["form"] = deploy_form.waiting(p) if listening and cloud["held"] else None
    dns = _choices(hosting.DNS, rows)
    ready = [d for d in dns if d["held"]]
    if ready:
        summaries["domain"] = ", ".join(d["name"] for d in ready) + ": keys set"
    return found | {
        "view": "steps",
        "steps": _steps(summaries),
        # Each picker opens on a provider whose keys are set: the first
        # cloud otherwise, no DNS provider (an sslip.io name).
        "clouds": clouds,
        "cloud_choice": _opens_on(clouds, clouds[0]["key"]),
        "dns": dns,
        "dns_choice": _opens_on(dns, ""),
    }
