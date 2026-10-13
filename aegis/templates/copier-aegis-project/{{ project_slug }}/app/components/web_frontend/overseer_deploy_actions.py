"""Overseer > Deployments' actions: a new server (a size and region the
provider sells, its price typed back, provision), then deploy, back up,
list backups, roll back and destroy.

Each is asked of ``aegis deploy-agent`` on the developer's machine through
the project's Redis (``app.components.deploy.agent``), so the SSH key
never enters the app, and comes back as its job, whose output the card
streams. A new server is offered on each provider whose token the app
holds (Overseer > Secrets, or ``.env``) or the agent does (its own
environment), from that provider's catalog: what it sells where, which the
agent fetches in the background and keeps an hour. Offered on the dev
build only: a deployed server is
redeployed from the dev Overseer or CI. The htmx Overseer only; the Flet
dashboard shows the commands.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import PROTOCOL, RefusedError, validate
from app.core.config import settings
from app.core.log import logger
from app.services.system import deploy_fit, hosting

from . import overseer_secrets
from .overseer_live import fragment_events
from .rendering import fragment

EVENTS = "/overseer/events/deployments/job"
EVENT = "deploy-job"
PARTIALS = "/partials/overseer/deployments"
JOB = "pages/overseer/deployments/_job.html"
PROVISION = "pages/overseer/deployments/_provision.html"
FIT = "pages/overseer/deployments/_fit.html"
INTERVAL_SECONDS = 1.0
AGENT_COMMAND = "aegis deploy-agent"
CD_COMMAND = "aegis deploy-cd-setup"
LIVE = ("provisioning", "ready")  # a provision record whose resources may exist
MIN_MEMORY_MB = 2048  # the smallest size offered by default: the stack needs it
# The actions asked from the card, each its job; the catalog is fetched
# in the background (``catalog_url``), not asked.
TITLES = {
    "provision": "New server",
    "deploy": "Deploy",
    "backup": "Back up",
    "backups": "Backups",
    "rollback": "Roll back",
    "destroy": "Destroy",
}
DEPLOYED = "This is a deployed server: deploy from the dev Overseer or CI."


def _deployed() -> bool:
    return settings.BUILD_ID != hosting.LOCAL


async def _held(beat: dict[str, Any]) -> set[str]:
    """The providers a server can be created on: their token is the app's
    (``app.core.secrets``) or the agent's (its heartbeat)."""
    return set(beat.get("providers") or ()) | await deploy_agent.tokens_here()


def _secrets_page() -> str | None:
    """Where a token can be set from here: the Secrets page, with the
    secrets component to keep it; None where only ``.env`` can."""
    return overseer_secrets.url() if overseer_secrets.has_component() else None


def _server_name() -> str | None:
    """The provisioned server's name, while what it made may still exist."""
    record = hosting.deploy_config().get("provision") or {}
    return record.get("server_name") if record.get("status") in LIVE else None


# The way from this machine to a server, in order. Provisioning deploys,
# so the server step ends with the app live there.
STEPS = (("agent", "Deploy agent"), ("where", "Where"), ("server", "Server"))
OWN_SERVER = "aegis deploy-init --host <your server's address>"


async def _agent() -> dict[str, Any]:
    """Whether the deploy agent is listening (``beat``, its heartbeat), or
    why it cannot be: no Redis to carry the asking, Redis not answering,
    nobody listening."""
    if not deploy_agent.has_redis():
        return {"state": "no-redis"}
    try:
        beat = await deploy_agent.agent()
    except Exception as exc:  # noqa: BLE001 - shown in the card, logged here
        logger.warning("Deploy agent heartbeat unreadable", error=str(exc))
        return {"state": "unreachable", "error": str(exc)}
    if beat is None:
        return {"state": "no-agent", "command": AGENT_COMMAND}
    return {"state": "ready", "beat": beat}


def _steps(summaries: dict[str, str]) -> list[dict[str, Any]]:
    """``STEPS``, each done (it has a summary), the one at hand (the first
    not done), or still to come."""
    found = []
    for key, title in STEPS:
        status = "done" if key in summaries else "todo"
        if status == "todo" and all(s["status"] == "done" for s in found):
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


def _server(config: dict[str, Any]) -> dict[str, Any]:
    """The server this project deploys to: the provision record's, else the
    one ``aegis deploy-init`` named."""
    box = config.get("server") or {}
    return hosting.deploys_to() or {
        "name": box.get("host", "Your server"),
        "logo": None,
        "facts": [("User", box.get("user")), ("Path", box.get("path"))],
        "console": None,
    }


async def context() -> dict[str, Any]:
    """The card, as one of three views: a deployed server (redeploys come
    from elsewhere), the steps to a server (none yet), or the server and
    what can be done to it."""
    if _deployed():
        return {"view": "deployed", "command": CD_COMMAND}
    agent = await _agent()
    listening = agent["state"] == "ready"
    shared = {
        "agent": agent,
        "partials": PARTIALS,
        "events": EVENTS,
        "event": EVENT,
        "job": await job_context() if listening else None,
    }
    config = hosting.deploy_config()
    if config.get("server"):
        return shared | {
            "view": "server",
            "server": _server(config),
            "destroy": _server_name(),
        }
    held = await _held(agent.get("beat") or {})
    providers = [p for p in hosting.PROVISIONABLE if p.key in held]
    summaries = {}
    if listening:
        beat = agent["beat"]
        summaries["agent"] = f"Listening on {beat['host']} (aegis {beat['version']})"
    if providers:
        summaries["where"] = ", ".join(p.name for p in providers) + ": token set"
    return shared | {
        "view": "steps",
        "steps": _steps(summaries),
        "providers": [_waiting(p) for p in providers] if listening else [],
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


async def job_context(job_id: str | None = None) -> dict[str, Any] | None:
    """A deploy job as the card shows it (the newest by default): its
    progress, the output's tail, a price to confirm, or, for a provision
    that failed part way, the destroy that cleans up after it."""
    found = await deploy_agent.job(job_id)
    if found is None:
        return None
    action = found.name.removeprefix(deploy_agent.JOB_PREFIX)
    if action not in TITLES:  # an action this page no longer asks
        return None
    result = found.result or {}
    failed_provision = action == "provision" and found.status == "failed"
    return {
        "id": found.job_id,
        "action": action,
        "title": TITLES.get(action, action),
        "status": found.status,
        "label": found.label,
        "error": found.error,
        "lines": result.get("lines") or [],
        "destroy": _server_name() if failed_provision else None,
        "partials": PARTIALS,
    }


async def render_job(job_id: str | None = None) -> str:
    return fragment(JOB, job=await job_context(job_id))


def events(max_frames: int | None = None) -> AsyncIterator[str]:
    """The newest deploy job over SSE, sent again only when it changes."""
    return fragment_events(EVENT, render_job, INTERVAL_SECONDS, max_frames)


def catalog_url(provider: str) -> str:
    return f"{PARTIALS}/catalog/{provider}"


def _memory(mb: int) -> str:
    return f"{mb} MB" if mb < 1024 else f"{mb / 1024:g} GB"


def _cheapest(size: dict[str, Any]) -> float:
    return min(float(price) for price in size["prices"].values())


def choice(
    sold: dict[str, Any], provider: hosting.Provider, form: dict[str, str]
) -> dict[str, Any]:
    """The new-server form over what ``provider`` sells (``sold``, its
    catalog): the size picked (the form's, else the provider's default,
    else the cheapest with ``MIN_MEMORY_MB``), a region that offers it (the
    form's, else the default, else the first by name), and its price. Sizes
    by group, cheapest first."""
    names = {r["slug"]: r["name"] for r in sold["regions"]}
    sizes = sorted(
        (s for s in sold["sizes"] if names.keys() & s["prices"]), key=_cheapest
    )
    if not sizes:
        raise RefusedError(f"{provider.name} offers no server to create right now.")
    by_slug = {s["slug"]: s for s in sizes}
    big_enough = [s for s in sizes if s["memory_mb"] >= MIN_MEMORY_MB] or sizes
    size = by_slug.get(form.get("size", "")) or by_slug.get(provider.size or "")
    size = size or big_enough[0]
    offered = sorted(
        (r for r in size["prices"] if r in names), key=lambda slug: names[slug]
    )
    region = next(
        (r for r in (form.get("region"), provider.region) if r in offered), offered[0]
    )
    groups: dict[str, list[dict[str, str]]] = {}
    for s in sizes:
        label = " · ".join(
            (_memory(s["memory_mb"]), f"{s['vcpus']} vCPU", f"{s['disk_gb']} GB")
        )
        groups.setdefault(s["group"], []).append({"id": s["slug"], "name": label})
    return {
        "sizes": [{"label": g, "options": options} for g, options in groups.items()],
        "size": size["slug"],
        "regions": [{"id": r, "name": f"{names[r]} ({r})"} for r in offered],
        "region": region,
        "price": size["prices"][region],
        "currency": sold["currency"],
    }


# A ready form reloads when a size or region is picked (htmx's own trigger
# filter, on the change bubbling up from the select).
PICKED = "change[target.name=='size'||target.name=='region']"


def _shown(provider: hosting.Provider) -> dict[str, Any]:
    return {
        "provider": provider.key,
        "name": provider.name,
        "url": catalog_url(provider.key),
    }


def _reload(url: str, job: str | None) -> dict[str, str]:
    """A fragment waiting on the agent: loaded as the page is, then, once
    the agent has been asked (``job``), asked again each second."""
    if not job:
        return {"url": url, "trigger": "load"}
    joined = "&" if "?" in url else "?"
    return {"url": f"{url}{joined}job={job}", "trigger": "load delay:1s"}


def _waiting(provider: hosting.Provider, job: str | None = None) -> dict[str, Any]:
    """The form while its catalog is on its way."""
    reload = _reload(catalog_url(provider.key), job)
    return _shown(provider) | {"state": "loading", "job": job, "reload": reload}


def fit_url(provider: str, size: str) -> str:
    return f"{PARTIALS}/fit/{provider}?size={size}"


async def _from_agent(
    action: str,
    args: dict[str, str],
    kept: Callable[[], Awaitable[dict[str, Any] | None]],
    job: str | None,
    by: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """What the agent keeps for ``action`` (``kept``), asking for it once
    when there is none: ``(found, None)``, or ``(None, job)`` while that
    ask (``job``) runs; RefusedError when it cannot be asked, or failed."""
    await request_args(action, args)
    if (found := await kept()) is not None:
        return found, None
    if not job:
        return None, await deploy_agent.enqueue(action, args, by)
    asked = await deploy_agent.job(job)
    if asked is not None and asked.status == "failed":
        raise RefusedError(asked.error or f"The deploy agent could not {action}.")
    return None, job


def _provisionable(key: str) -> hosting.Provider:
    found = next((p for p in hosting.PROVISIONABLE if p.key == key), None)
    if found is None:
        raise RefusedError(f"Servers are not created on {key} from here.")
    return found


async def provision_form(key: str, form: dict[str, str], by: str) -> dict[str, Any]:
    """One provider's new-server form: its catalog's sizes and regions;
    while there is none, the agent asked for it (once: ``form["job"]`` is
    that ask) and the form waiting on it, or why it failed."""
    provider = _provisionable(key)
    shown = _shown(provider)
    try:
        sold, job = await _from_agent(
            "catalog",
            {"provider": key},
            lambda: deploy_agent.catalog(key),
            form.get("job"),
            by,
        )
        if sold is None:
            return _waiting(provider, job)
        picked = choice(sold, provider, form)
    except RefusedError as exc:
        return shown | {"state": "failed", "error": str(exc)}
    entered = {k: form.get(k, "") for k in ("domain", "email")}
    reload = {"url": shown["url"], "trigger": PICKED}
    fit = {"state": "loading", "reload": _reload(fit_url(key, picked["size"]), None)}
    ready = {"state": "ready", "partials": PARTIALS, "reload": reload, "fit": fit}
    return shown | picked | entered | ready


async def fit_panel(key: str, form: dict[str, str], by: str) -> dict[str, Any]:
    """Whether the size picked (``form["size"]``) has room for the stack
    (``deploy_fit``), from the agent's measurement of it; while there is
    none, the agent asked (once) and the panel waiting, or why it failed."""
    provider = _provisionable(key)
    url = fit_url(key, form.get("size", ""))
    try:
        sold = await deploy_agent.catalog(provider.key) or {}
        size = next(
            (s for s in sold.get("sizes", ()) if s["slug"] == form.get("size")), None
        )
        if size is None:
            raise RefusedError("Pick a size the provider sells.")
        found, job = await _from_agent(
            "footprint", {}, deploy_agent.footprint, form.get("job"), by
        )
    except RefusedError as exc:
        return {"state": "failed", "error": str(exc)}
    if found is None:
        return {"state": "loading", "reload": _reload(url, job)}
    return {"state": "ready"} | deploy_fit.fit(found, size)


async def render_fit(key: str, form: dict[str, str], by: str) -> str:
    return fragment(FIT, f=await fit_panel(key, form, by))


async def render_provision_form(key: str, form: dict[str, str], by: str) -> str:
    return fragment(PROVISION, p=await provision_form(key, form, by))


async def _confirmed(form: dict[str, str]) -> dict[str, str]:
    """A provision of a size and region the provider sells (its catalog),
    once the price shown is typed back: the catalog's price, never the
    form's."""
    provider = _provisionable(form.get("provider", ""))
    sold = await deploy_agent.catalog(provider.key)
    if sold is None:
        raise RefusedError("The sizes and prices have expired: reload the page.")
    picked = choice(sold, provider, form)
    if (picked["size"], picked["region"]) != (form.get("size"), form.get("region")):
        raise RefusedError(f"{provider.name} does not offer that size in that region.")
    if form.get("typed", "").strip() != picked["price"]:
        raise RefusedError(f"Type the price, {picked['price']}, to create the server.")
    spec = PROTOCOL["actions"]["provision"]
    keys = (*spec["required"], *spec.get("optional", ()))
    return validate("provision", {k: (form | picked).get(k, "") for k in keys})


async def request_args(action: str, form: dict[str, str]) -> dict[str, str]:
    """What to ask the agent for ``action``, from its form, checked as far
    as the app can (the agent checks again); refused with the reason."""
    if _deployed():
        raise RefusedError(DEPLOYED)
    beat = await deploy_agent.agent()
    if beat is None:
        raise RefusedError(f"No deploy agent is listening: start {AGENT_COMMAND}.")
    if form.get("provider") and form["provider"] not in await _held(beat):
        raise RefusedError(
            f"No token to create a server on {form['provider']}: set it in "
            "Overseer > Secrets (or .env), or where the deploy agent runs."
        )
    if action == "provision":
        return await _confirmed(form)
    args = validate(action, form)
    if action == "destroy" and args["confirm"] != _server_name():
        raise RefusedError("Type the server's name exactly to destroy it.")
    return args
