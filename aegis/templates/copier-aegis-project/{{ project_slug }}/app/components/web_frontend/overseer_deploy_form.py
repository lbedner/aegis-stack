"""Overseer > Deployments' new-server form: each cloud's catalog (the
sizes and regions it sells, with the price to type back), whether the
stack fits the size picked (``deploy_fit``), what the account already runs
and costs (``deploy_spend``), and what each action form asks of the deploy
agent, checked as far as the app can. Offered on each cloud whose token
the app holds (Overseer > Secrets, or ``.env``) or the agent does (its
own environment). Its panels load on their own while
the agent answers; the job they start is ``overseer_deploy_actions``'.
"""

import asyncio
from typing import Any
from urllib.parse import urlencode

from app.components.deploy import agent as deploy_agent
from app.components.deploy.protocol import (
    PROTOCOL,
    PROVISION_STEPS,
    RefusedError,
    validate,
)
from app.core import exposure
from app.core.config import settings
from app.core.formatting import format_bytes
from app.services.system import deploy_fit, deploy_spend, hosting

from .overseer_deploy_actions import (
    AGENT_COMMAND,
    PARTIALS,
    server_name,
    stopped,
)

PROVISION = "pages/overseer/deployments/_provision.html"
FIT = "pages/overseer/deployments/_fit.html"
ACCOUNT = "pages/overseer/deployments/_account.html"
ROLLBACK = f"{PARTIALS}/rollback"  # the backups a rollback picks from
ROLLBACK_TEMPLATE = "pages/overseer/deployments/_rollback.html"
MIN_MEMORY_MB = 2048  # the smallest size offered by default: the stack needs it
DEPLOYED = "This is a deployed server: deploy from the dev Overseer or CI."


async def held(beat: dict[str, Any]) -> set[str]:
    """The providers a server can be created on: their token is the app's
    (``app.core.secrets``) or the agent's (its heartbeat)."""
    return set(beat.get("providers") or ()) | await deploy_agent.tokens_here()


async def accounts(agent: dict[str, Any]) -> list[dict[str, Any]]:
    """Each connected cloud account's servers and what they cost, as the
    agent last found them (kept a few minutes); where that has expired,
    waiting on it, asked again in the background as the page opens."""
    tokens = await held(agent.get("beat") or {})
    return [
        _account(p, None, await deploy_agent.kept("account", {"provider": p.key}))
        for p in hosting.PROVISIONABLE
        if p.key in tokens
    ]


def panel_path(panel: str, provider: str) -> str:
    """Where a part of the new-server form (``PANELS``) loads from."""
    return f"{PARTIALS}/{panel}/{provider}"


def _with(path: str, **params: str) -> str:
    """``path`` with what it is asked for (empty values left out)."""
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{path}?{query}" if query else path


def panel_url(panel: str, provider: str, **params: str) -> str:
    """``panel_path`` with what it is asked for."""
    return _with(panel_path(panel, provider), **params)


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
    path: str,
    job: str | None,
    first: str = "load",
    **picked: str,
) -> dict[str, Any]:
    """A part waiting on the agent (loaded from ``path``): loaded on
    ``first`` (as the page is, by default), then, once the agent has been
    asked (``job``), polled each second until it answers (a poll still
    waiting swaps nothing: the routes' ``part``)."""
    url = _with(path, **picked, job=job or "")
    return {
        "state": "loading",
        "reload": {"url": url, "trigger": "every 1s" if job else first},
    }


def _failed(path: str, exc: RefusedError, **picked: str) -> dict[str, Any]:
    """A part that could not be had: why, and where asking again loads it
    from (``path``)."""
    return {"state": "failed", "error": str(exc), "retry": _with(path, **picked)}


# Instead of a new server, one of your own: name it, then deploy to it
# (the terminal's way, as ``by_hand`` lists it).
OWN_SERVER = (
    {
        "name": "Name it (AWS, or any machine you can SSH into)",
        "command": "aegis deploy-init --host <your server's address>",
    },
    {"name": "Then deploy to it", "command": hosting.BY_KEY["server"].command},
)


def _shown(provider: hosting.Provider) -> dict[str, Any]:
    return {
        "provider": provider.key,
        "name": provider.name,
        "own": OWN_SERVER,
        "url": panel_url("catalog", provider.key),
    }


def waiting(provider: hosting.Provider) -> dict[str, Any]:
    """The form before its catalog is asked for: asked once it shows (its
    cloud picked), not for every cloud on opening the page."""
    return _shown(provider) | _loading(
        panel_path("catalog", provider.key), None, "intersect once"
    )


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
    found = hosting.provider(key)
    if found is None or found not in hosting.PROVISIONABLE:
        raise RefusedError(f"Servers are not created on {key} from here.")
    return found


def _fit(
    provider: hosting.Provider, picked: dict[str, Any], found: dict[str, Any] | None
) -> dict[str, Any]:
    """Whether the size ``picked`` has room for the stack (``deploy_fit``),
    from the agent's measurement (``found``); without one, waiting on it."""
    if found is None:
        return _loading(panel_path("fit", provider.key), None, size=picked["size"])
    return {"state": "ready"} | deploy_fit.fit(found, picked["size_spec"])


def _named(provider: hosting.Provider) -> dict[str, Any]:
    """Which account a panel is about: its name, and its logo (the
    Overview's mark for it)."""
    return {"name": provider.name, "logo": provider.logo}


def _account(
    provider: hosting.Provider,
    picked: dict[str, Any] | None,
    found: dict[str, Any] | None,
) -> dict[str, Any]:
    """What the account already runs and costs, with the server ``picked``
    when one is being bought (``deploy_spend``), from the agent's look at
    it; without one, waiting on it."""
    shown = _named(provider)
    where = {"size": picked["size"], "region": picked["region"]} if picked else {}
    if found is None:
        return shown | _loading(panel_path("account", provider.key), None, **where)
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
            return shown | _loading(panel_path("catalog", provider.key), job)
        picked = choice(sold, provider, form)
    except RefusedError as exc:
        return shown | _failed(panel_path("catalog", provider.key), exc)
    optional = PROTOCOL["actions"]["provision"]["optional"]
    entered = {k: form.get(k, "") for k in optional}
    footprint, account = await asyncio.gather(
        deploy_agent.kept("footprint", {}), deploy_agent.kept("account", args)
    )
    panels = {
        "fit": _fit(provider, picked, footprint),
        "account": _account(provider, picked, account),
    }
    reload = {"url": shown["url"], "trigger": PICKED}
    ready = {"state": "ready", "partials": PARTIALS, "reload": reload}
    # Only a SQLite database can be brought along (``aegis deploy-upload-db``).
    sqlite = getattr(settings, "DATABASE_URL", "").startswith("sqlite")
    bring = {"bring": PROVISION_STEPS["data"] if sqlite else None}
    return shown | picked | entered | ready | panels | bring


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
            return _loading(panel_path("fit", provider.key), job, size=size)
        picked = choice(await _catalog(provider), provider, form)
        if picked["size"] != size:
            raise RefusedError("Pick a size the provider sells.")
    except RefusedError as exc:
        return _failed(panel_path("fit", provider.key), exc, size=size)
    return _fit(provider, picked, found)


async def account_panel(
    provider: hosting.Provider, form: dict[str, str], by: str
) -> dict[str, Any]:
    """What the account already runs and costs, with the size and region
    picked; while the agent has not looked, it asked (once) and the panel
    waiting, or why it failed (a token without the scope to list says
    which)."""
    where = {"size": form.get("size", ""), "region": form.get("region", "")}
    shown = _named(provider)
    try:
        args = {"provider": provider.key}
        found, job = await _from_agent("account", args, form.get("job"), by)
        if found is None:
            return shown | _loading(panel_path("account", provider.key), job, **where)
        sold = await _catalog(provider) if where["size"] else None
        picked = choice(sold, provider, form) if sold else None
    except RefusedError as exc:
        return shown | _failed(panel_path("account", provider.key), exc, **where)
    return _account(provider, picked, found)


def _backup_option(backup: dict[str, Any]) -> dict[str, str]:
    """A backup as the rollback's select offers it: its name, size, and
    whether it holds the database."""
    held = "with the database" if backup["database"] else "no database"
    return {
        "id": backup["name"],
        "name": f"{backup['name']} · {backup['size']} · {held}",
    }


async def rollback_panel(form: dict[str, str], by: str) -> dict[str, Any]:
    """The backups a rollback can go to, newest first (the agent's look at
    the server); while it has not looked, it asked (once) and the panel
    waiting, or why it failed."""
    try:
        found, job = await _from_agent("backups", {}, form.get("job"), by)
    except RefusedError as exc:
        return _failed(ROLLBACK, exc)
    if found is None:
        return _loading(ROLLBACK, job)
    options = [_backup_option(b) for b in found["backups"]]
    return {"state": "ready", "backups": options, "partials": PARTIALS}


# The rollback's backups, as the Overview first draws them: asked for as
# the card loads.
ROLLBACK_WAITING = _loading(ROLLBACK, None)


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
    if exposure.deployed():
        raise RefusedError(DEPLOYED)
    beat = await _listening()
    if form.get("provider") and form["provider"] not in await held(beat):
        raise RefusedError(
            f"No token to create a server on {form['provider']}: set it in "
            "Overseer > Secrets (or .env), or where the deploy agent runs."
        )
    if action == "provision":
        return await _confirmed(form)
    if action == "resume" and stopped() is None:
        raise RefusedError("No server stopped part way: there is nothing to resume.")
    args = validate(action, form)
    if action == "destroy" and args["confirm"] != server_name():
        raise RefusedError("Type the server's name exactly to destroy it.")
    if action == "rollback":
        kept = await deploy_agent.kept("backups", {}) or {}
        if args["backup"] not in {b["name"] for b in kept.get("backups", ())}:
            raise RefusedError("That backup is not on the server: reload the page.")
    return args
