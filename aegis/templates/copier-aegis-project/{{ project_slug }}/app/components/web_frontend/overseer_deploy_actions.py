"""Overseer > Deployments' actions: a new server (a size and region the
provider sells, its price typed back, provision), then deploy, back up,
list backups, roll back and destroy.

Each is asked of ``aegis deploy-agent`` on the developer's machine through
the project's Redis (``app.components.deploy.agent``), so the SSH key
never enters the app, and comes back as its job, whose output the card
streams. A new server is offered on each provider whose token the app
holds (Overseer > Secrets, or ``.env``) or the agent does (its own
environment), from that provider's catalog: what it sells where, which the
agent fetches in the background, with whether the stack fits each size.
Offered on the dev build only: a deployed server is redeployed from the
dev Overseer or CI. The htmx Overseer only; the Flet
dashboard shows the commands.
"""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import PROTOCOL, RefusedError, validate
from app.core.config import settings
from app.core.formatting import format_bytes
from app.core.log import logger
from app.services.system import deploy_fit, deploy_spend, hosting

from .overseer_live import fragment_events
from .rendering import fragment

EVENTS = "/overseer/events/deployments/job"
EVENT = "deploy-job"
PARTIALS = "/partials/overseer/deployments"
JOB = "pages/overseer/deployments/_job.html"
PROVISION = "pages/overseer/deployments/_provision.html"
FIT = "pages/overseer/deployments/_fit.html"
ACCOUNT = "pages/overseer/deployments/_account.html"
INTERVAL_SECONDS = 1.0
AGENT_COMMAND = "aegis deploy-agent"
CD_COMMAND = "aegis deploy-cd-setup"
LIVE = ("provisioning", "ready")  # a provision record whose resources may exist
MIN_MEMORY_MB = 2048  # the smallest size offered by default: the stack needs it
# The actions asked from the card, each its job; the protocol's ``kept``
# ones are fetched in the background, never asked.
TITLES = {
    "provision": "New server",
    "deploy": "Deploy",
    "backup": "Back up",
    "backups": "Backups",
    "rollback": "Roll back",
    "destroy": "Destroy",
}
DEPLOYED = "This is a deployed server: deploy from the dev Overseer or CI."


def deployed() -> bool:
    return settings.BUILD_ID != hosting.LOCAL


async def held(beat: dict[str, Any]) -> set[str]:
    """The providers a server can be created on: their token is the app's
    (``app.core.secrets``) or the agent's (its heartbeat)."""
    return set(beat.get("providers") or ()) | await deploy_agent.tokens_here()


def server_name() -> str | None:
    """The provisioned server's name, while what it made may still exist."""
    record = hosting.deploy_config().get("provision") or {}
    return record.get("server_name") if record.get("status") in LIVE else None


async def _agent() -> dict[str, Any]:
    """Whether the deploy agent is listening (``beat``, its heartbeat), or
    why it cannot be: no Redis to carry the asking, Redis not answering,
    nobody listening, or one older than this app."""
    if not deploy_agent.has_redis():
        return {"state": "no-redis"}
    try:
        beat = await deploy_agent.agent()
    except RefusedError as exc:  # Redis not answering: shown in the card
        logger.warning("Deploy agent heartbeat unreadable", error=str(exc))
        return {"state": "unreachable", "error": str(exc)}
    if beat is None:
        return {"state": "no-agent", "command": AGENT_COMMAND}
    if deploy_agent.stale(beat):
        return {"state": "stale", "error": deploy_agent.STALE}
    return {"state": "ready", "beat": beat}


# Where nothing is asked from here: a deployed server.
DEPLOYED_VIEW = {"view": "deployed", "command": CD_COMMAND}


async def shared() -> dict[str, Any]:
    """What both pages show of the agent: whether it can be asked (and why
    not), and its newest job, streamed."""
    agent = await _agent()
    listening = agent["state"] == "ready"
    return {
        "agent": agent,
        "partials": PARTIALS,
        "events": EVENTS,
        "event": EVENT,
        "job": await job_context() if listening else None,
    }


async def accounts(agent: dict[str, Any]) -> list[dict[str, Any]]:
    """Each connected cloud account's servers and what they cost, as the
    agent last found them; where it has not looked, waiting on it (asked
    in the background, never on opening the page)."""
    tokens = await held(agent.get("beat") or {})
    return [
        _account(p, None, await deploy_agent.kept("account", {"provider": p.key}))
        for p in hosting.PROVISIONABLE
        if p.key in tokens
    ]


async def job_context(job_id: str | None = None) -> dict[str, Any] | None:
    """A deploy job as the card shows it (the newest by default): its
    progress and the output's tail, or, for a provision that failed part
    way, the destroy that cleans up after it. None for one the card does
    not ask (a background fetch, or an action the protocol has dropped)."""
    found = await deploy_agent.job(job_id)
    if found is None:
        return None
    action = found.name.removeprefix(deploy_agent.JOB_PREFIX)
    if not asked_from_card(action):
        return None
    result = found.result or {}
    failed_provision = action == "provision" and found.status == "failed"
    return {
        "action": action,
        "title": TITLES[action],
        "status": found.status,
        "label": found.label,
        "error": found.error,
        "lines": result.get("lines") or [],
        "destroy": server_name() if failed_provision else None,
        "partials": PARTIALS,
    }


async def render_job(job_id: str | None = None) -> str:
    return fragment(JOB, job=await job_context(job_id))


def events(max_frames: int | None = None) -> AsyncIterator[str]:
    """The newest deploy job over SSE, sent again only when it changes."""
    return fragment_events(EVENT, render_job, INTERVAL_SECONDS, max_frames)


def asked_from_card(action: str) -> bool:
    """An action the card's buttons ask (each its job, titled): ``TITLES``,
    the protocol's actions that are not ``kept``."""
    return action in TITLES


def panel_path(panel: str, provider: str) -> str:
    """Where a part of the new-server form (``PANELS``) loads from."""
    return f"{PARTIALS}/{panel}/{provider}"


def panel_url(panel: str, provider: str, **params: str) -> str:
    """``panel_path`` with what it is asked for (empty values left out)."""
    query = urlencode({k: v for k, v in params.items() if v})
    return (
        f"{panel_path(panel, provider)}?{query}"
        if query
        else panel_path(panel, provider)
    )


def _cheapest(size: dict[str, Any]) -> float:
    return min(float(price) for price in size["prices"].values())


def choice(
    sold: dict[str, Any], provider: hosting.Provider, form: dict[str, str]
) -> dict[str, Any]:
    """The new-server form over what ``provider`` sells (``sold``, its
    catalog): the size picked (the form's, else the provider's default,
    else the cheapest with ``MIN_MEMORY_MB``), a region that offers it (the
    form's, else the default, else the first by name), and its price (as
    the provider says it, to type back, and in cents). Sizes by group,
    cheapest first."""
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
        memory = format_bytes(s["memory_mb"] * deploy_fit.MIB)
        label = f"{memory} · {s['vcpus']} vCPU · {s['disk_gb']} GB"
        groups.setdefault(s["group"], []).append({"id": s["slug"], "name": label})
    return {
        "sizes": [{"label": g, "options": options} for g, options in groups.items()],
        "size": size["slug"],
        "size_spec": size,
        "regions": [{"id": r, "name": f"{names[r]} ({r})"} for r in offered],
        "region": region,
        "price": size["prices"][region],
        "price_cents": deploy_spend.cents(size["prices"][region]),
        "currency": sold["currency"],
    }


# A ready form reloads when a size or region is picked (htmx's own trigger
# filter, on the change bubbling up from the select).
PICKED = "change[target.name=='size'||target.name=='region']"


def _loading(
    panel: str, provider: hosting.Provider, job: str | None, **picked: str
) -> dict[str, Any]:
    """A part of the form waiting on the agent: loaded as the page is, then,
    once the agent has been asked (``job``), polled each second until it
    answers (a poll still waiting swaps nothing: the routes' ``_part``)."""
    url = panel_url(panel, provider.key, **picked, job=job or "")
    return {
        "state": "loading",
        "reload": {"url": url, "trigger": "every 1s" if job else "load"},
    }


def _failed(
    panel: str, provider: hosting.Provider, exc: RefusedError, **picked: str
) -> dict[str, Any]:
    """A part of the form that could not be had: why, and where asking
    again loads it from."""
    retry = panel_url(panel, provider.key, **picked)
    return {"state": "failed", "error": str(exc), "retry": retry}


def _shown(provider: hosting.Provider) -> dict[str, Any]:
    return {
        "provider": provider.key,
        "name": provider.name,
        "logo": provider.logo,
        "url": panel_url("catalog", provider.key),
    }


def waiting(provider: hosting.Provider) -> dict[str, Any]:
    """The form before its catalog is asked for."""
    return _shown(provider) | _loading("catalog", provider, None)


async def _listening() -> dict[str, Any]:
    """The listening agent's heartbeat; refused when none is, or one older
    than this app."""
    beat = await deploy_agent.agent()
    if beat is None:
        raise RefusedError(f"No deploy agent is listening: start {AGENT_COMMAND}.")
    if deploy_agent.stale(beat):
        raise RefusedError(deploy_agent.STALE)
    return beat


async def _from_agent(
    action: str, args: dict[str, str], job: str | None, by: str
) -> tuple[dict[str, Any] | None, str | None]:
    """What the agent keeps for ``action``, asking for it once when there
    is none: ``(found, None)``, or ``(None, job)`` while that ask (``job``)
    runs; RefusedError when it cannot be asked, failed, or will not be
    answered (its job gone, the agent stopped), so no poll runs forever.
    What is kept is read first: a poll that finds it costs one read."""
    if (found := await deploy_agent.kept(action, args)) is not None:
        return found, None
    if job:
        asked = await deploy_agent.job(job)
        if asked is None or asked.status == "done":
            raise RefusedError("The deploy agent's answer is gone: ask again.")
        if asked.status == "failed":
            raise RefusedError(asked.error or f"The deploy agent could not {action}.")
        await _listening()
        return None, job
    await request_args(action, args)
    return None, await deploy_agent.enqueue(action, args, by)


async def _catalog(provider: hosting.Provider) -> dict[str, Any]:
    """What ``provider`` sells, as the form was built from it; refused once
    it has expired."""
    sold = await deploy_agent.kept("catalog", {"provider": provider.key})
    if sold is None:
        raise RefusedError("The sizes and prices have expired: reload the page.")
    return sold


def provisionable(key: str) -> hosting.Provider:
    """The provider servers are created on from here named ``key``."""
    found = next((p for p in hosting.PROVISIONABLE if p.key == key), None)
    if found is None:
        raise RefusedError(f"Servers are not created on {key} from here.")
    return found


def _fit(
    provider: hosting.Provider, picked: dict[str, Any], found: dict[str, Any] | None
) -> dict[str, Any]:
    """Whether the size ``picked`` has room for the stack (``deploy_fit``),
    from the agent's measurement (``found``); without one, waiting on it."""
    if found is None:
        return _loading("fit", provider, None, size=picked["size"])
    return {"state": "ready"} | deploy_fit.fit(found, picked["size_spec"])


def _account(
    provider: hosting.Provider,
    picked: dict[str, Any] | None,
    found: dict[str, Any] | None,
) -> dict[str, Any]:
    """What the account already runs and costs, with the server ``picked``
    when one is being bought (``deploy_spend``), from the agent's look at
    it; without one, waiting on it."""
    shown = {"name": provider.name}
    where = {"size": picked["size"], "region": picked["region"]} if picked else {}
    if found is None:
        return shown | _loading("account", provider, None, **where)
    price = picked["price"] if picked else None
    return shown | {"state": "ready"} | deploy_spend.spend(found, price)


async def provision_form(
    provider: hosting.Provider, form: dict[str, str], by: str
) -> dict[str, Any]:
    """One provider's new-server form: its catalog's sizes and regions,
    whether the size picked fits, and what the account already runs; while
    there is no catalog, the agent asked for it (once: ``form["job"]`` is
    that ask) and the form waiting on it, or why it failed."""
    shown = _shown(provider)
    args = {"provider": provider.key}
    try:
        sold, job = await _from_agent("catalog", args, form.get("job"), by)
        if sold is None:
            return shown | _loading("catalog", provider, job)
        picked = choice(sold, provider, form)
    except RefusedError as exc:
        return shown | _failed("catalog", provider, exc)
    optional = PROTOCOL["actions"]["provision"]["optional"]
    entered = {k: form.get(k, "") for k in optional}
    panels = {
        "fit": _fit(provider, picked, await deploy_agent.kept("footprint", {})),
        "account": _account(provider, picked, await deploy_agent.kept("account", args)),
    }
    reload = {"url": shown["url"], "trigger": PICKED}
    ready = {"state": "ready", "partials": PARTIALS, "reload": reload}
    return shown | picked | entered | ready | panels


async def fit_panel(
    provider: hosting.Provider, form: dict[str, str], by: str
) -> dict[str, Any]:
    """Whether the size picked (``form["size"]``) has room for the stack,
    from the agent's measurement of it; while there is none, the agent
    asked (once) and the panel waiting, or why it failed. The catalog is
    read only once there is something to fit."""
    size = form.get("size", "")
    try:
        found, job = await _from_agent("footprint", {}, form.get("job"), by)
        if found is None:
            return _loading("fit", provider, job, size=size)
        picked = choice(await _catalog(provider), provider, form)
        if picked["size"] != size:
            raise RefusedError("Pick a size the provider sells.")
    except RefusedError as exc:
        return _failed("fit", provider, exc, size=size)
    return _fit(provider, picked, found)


async def account_panel(
    provider: hosting.Provider, form: dict[str, str], by: str
) -> dict[str, Any]:
    """What the account already runs and costs, with the size and region
    picked; while the agent has not looked, it asked (once) and the panel
    waiting, or why it failed (a token without the scope to list says
    which)."""
    where = {"size": form.get("size", ""), "region": form.get("region", "")}
    shown = {"name": provider.name}
    try:
        args = {"provider": provider.key}
        found, job = await _from_agent("account", args, form.get("job"), by)
        if found is None:
            return shown | _loading("account", provider, job, **where)
        sold = await _catalog(provider) if where["size"] else None
        picked = choice(sold, provider, form) if sold else None
    except RefusedError as exc:
        return shown | _failed("account", provider, exc, **where)
    return _account(provider, picked, found)


# The new-server form's parts, each loaded on its own while the agent
# answers: its builder, template, and the name the template reads it by.
PANELS = {
    "catalog": (provision_form, PROVISION, "p"),
    "fit": (fit_panel, FIT, "f"),
    "account": (account_panel, ACCOUNT, "f"),
}


async def _confirmed(form: dict[str, str]) -> dict[str, str]:
    """A provision of a size and region the provider sells (its catalog),
    once the price shown is typed back: the catalog's price, never the
    form's."""
    provider = provisionable(form.get("provider", ""))
    picked = choice(await _catalog(provider), provider, form)
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
    if deployed():
        raise RefusedError(DEPLOYED)
    beat = await _listening()
    if form.get("provider") and form["provider"] not in await held(beat):
        raise RefusedError(
            f"No token to create a server on {form['provider']}: set it in "
            "Overseer > Secrets (or .env), or where the deploy agent runs."
        )
    if action == "provision":
        return await _confirmed(form)
    args = validate(action, form)
    if action == "destroy" and args["confirm"] != server_name():
        raise RefusedError("Type the server's name exactly to destroy it.")
    return args
