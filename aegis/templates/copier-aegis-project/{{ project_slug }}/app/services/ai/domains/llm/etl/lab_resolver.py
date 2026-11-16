"""Who MADE a model, answered by the public model registry.

The catalog's vendor is who SERVES a model (ollama, a gateway); the lab
is who published its weights. That cannot be read off the model id: labs
do not confine themselves to one product line, so a prefix table is
stale the week one of them ships under a new name. The registry's org
namespace is the durable answer, and derivative uploads (quantizations,
fine-tunes) name the repository they came from, so a re-upload points at
its origin instead of claiming the model.
"""

import asyncio
import base64
from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel import Session

from app.core.concurrency import fanout
from app.core.log import logger
from app.core.safe_fetch import BlockedAddressError, fetch_image
from app.services.ai.domains.llm.etl import queries
from app.services.ai.models.llm import (
    ROLE_MAKER,
    LLMOrg,
    LLMOrgRole,
)

_SEARCH_URL = "https://huggingface.co/api/models"
_ORG_URL = "https://huggingface.co/api/organizations/{slug}/overview"
_TIMEOUT = 8.0
_CANDIDATES = 5
# Lookups a sync runs at once: enough to hide the registry's latency, few
# enough that it does not notice.
_LOOKUPS = 8
# An org's name and logo as one run read them, by slug: its models share
# the read (``resolve_lab``).
Orgs = dict[str, "asyncio.Task[tuple[str, str | None]]"]


@dataclass(frozen=True)
class LabInfo:
    """A model's publishing org, as the registry states it."""

    slug: str
    name: str
    homepage: str
    icon_b64: str | None = None


def strip_local_tag(model_id: str) -> str:
    """The model's NAME, without runner prefix, tag, or quantization.

    ``ollama/qwen2.5-coder:14b`` and ``muse-glimmer:30b-mlx-128k`` both
    name one published model; the size and format after the colon are a
    local packaging detail the registry does not share.
    """
    return model_id.split("/")[-1].split(":")[0]


def _base_model_of(repo: dict[str, Any]) -> str | None:
    """The repository a derivative was built from, if it declares one."""
    base = repo.get("base_model")
    if base is None:
        base = (repo.get("cardData") or {}).get("base_model")
    if isinstance(base, list):
        return str(base[0]) if base else None
    return str(base) if base else None


def pick_repo(candidates: list[dict[str, Any]], name: str) -> str | None:
    """The repository that IS this model, from a registry search.

    Popularity does not decide it: a quantizer's GGUF upload routinely
    outranks the lab's own weights. A derivative names its origin, so
    it yields to that; otherwise the repo whose own name matches most
    closely wins, and nothing resembling the model resolves to nothing
    rather than borrowing a stranger's identity.
    """
    wanted = name.replace("-", "").replace("_", "").casefold()

    def normalized(repo: dict[str, Any]) -> str:
        repo_id = str(repo.get("modelId") or "")
        return repo_id.split("/")[-1].replace("-", "").replace("_", "").casefold()

    matches = [
        repo
        for repo in candidates
        if repo.get("modelId") and normalized(repo).startswith(wanted)
    ]
    if not matches:
        return None
    # Closest name wins, not the most downloaded: derivatives append to
    # the original's name (``-GGUF``, ``-Abliterated``), so the shortest
    # match is the weights everyone else built on.
    best = min(matches, key=lambda repo: len(normalized(repo)))
    return _base_model_of(best) or str(best["modelId"])


async def _org_avatar(client: httpx.AsyncClient, url: str | None) -> str | None:
    """The org's own logo as base64 - the same currency vendor and payee
    icons already speak, so the UI needs no second image path.

    The URL is the registry's choice, not ours, so it goes through the
    guarded fetch: public addresses only, every redirect checked (#493).
    """
    if not url:
        return None
    try:
        image = await fetch_image(client, url)
    except (httpx.HTTPError, BlockedAddressError) as exc:
        logger.warning(f"Lab avatar fetch failed for {url}: {exc}")
        return None
    return base64.b64encode(image).decode() if image else None


async def _org(client: httpx.AsyncClient, slug: str) -> tuple[str, str | None]:
    """An org's display name and logo (base64): its slug and no logo when
    it has no overview."""
    org = await client.get(_ORG_URL.format(slug=slug))
    if org.status_code != 200:
        return slug, None
    payload = org.json()
    display = str(payload.get("fullname") or slug)
    return display, await _org_avatar(client, payload.get("avatarUrl"))


async def resolve_lab(model_id: str, orgs: Orgs | None = None) -> LabInfo | None:
    """The lab that published a model, or None. ``orgs`` is what this run
    has read of each org, so a lab's models read its overview once.

    Network-bound and best-effort: a registry that is unreachable, a
    model nobody published, and an org without an overview all resolve
    to None, which the catalog stores as "lab unknown" and the UI
    renders as no mark at all.
    """
    name = strip_local_tag(model_id)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            search = await client.get(
                _SEARCH_URL,
                params={"search": name, "limit": _CANDIDATES, "full": "true"},
            )
            search.raise_for_status()
            repo_id = pick_repo(list(search.json()), name)
            if repo_id is None:
                return None
            slug = repo_id.split("/")[0]
            known = {} if orgs is None else orgs
            if slug not in known:
                known[slug] = asyncio.ensure_future(_org(client, slug))
            display, icon_b64 = await known[slug]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(f"Lab lookup failed for {model_id}: {exc}")
        return None
    return LabInfo(
        slug=slug,
        name=display,
        homepage=f"https://huggingface.co/{slug}",
        icon_b64=icon_b64,
    )


def _grant_role(
    session: Session, org: LLMOrg, role: str, held: set[tuple[int, str]]
) -> None:
    """Record a hat this org wears; roles are additive and idempotent.
    ``held`` is every (org_id, role) already recorded, read once by the
    caller - a brand-new org holds none."""
    if org.id is None or (org.id, role) in held:
        return
    held.add((org.id, role))
    session.add(LLMOrgRole(org_id=org.id, role=role))


async def attach_labs(session: Session, model_ids: list[str]) -> None:
    """Attach each model to the org that published it.

    One registry lookup per model that has no lab yet, so a re-sync
    of an unchanged catalog costs nothing, run a few at a time and each
    org read once. A model the registry does not know keeps a null lab -
    unmarked beats mislabelled.

    Every lookup runs before anything is written: a write left pending
    across a network call holds SQLite's lock - the one every other
    process is waiting for - and committing per model instead expired
    every row read, so each next one re-read itself.
    """
    models = queries.llms_by_model_ids(session, model_ids)
    unlabelled = [
        models[i] for i in model_ids if i in models and models[i].made_by_org_id is None
    ]
    orgs: Orgs = {}
    found = await fanout(
        lambda model: resolve_lab(model.model_id, orgs), unlabelled, limit=_LOOKUPS
    )
    labs = [
        (model, outcome.value)
        for model, outcome in zip(unlabelled, found, strict=True)
        if isinstance(outcome.value, LabInfo)
    ]
    if not labs:
        return
    orgs = {org.slug: org for org in queries.all_rows(session, LLMOrg)}
    held = {(r.org_id, r.role) for r in queries.all_rows(session, LLMOrgRole)}
    for model, info in labs:
        # The maker may already exist as a SERVING org (OpenAI serves
        # what it builds); that is one row wearing a second hat, not a
        # second row.
        org = orgs.get(info.slug)
        if org is None:
            org = LLMOrg(
                slug=info.slug,
                name=info.name,
                homepage=info.homepage,
                icon_b64=info.icon_b64,
                source="huggingface",
            )
            session.add(org)
            session.flush()
            orgs[info.slug] = org
        elif info.icon_b64 and not org.icon_b64:
            org.icon_b64 = info.icon_b64
            session.add(org)
        _grant_role(session, org, ROLE_MAKER, held)
        model.made_by_org_id = org.id
        session.add(model)
    session.commit()
