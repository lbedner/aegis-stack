"""Who MADE a model, answered by the public model registry.

The catalog's vendor is who SERVES a model (ollama, a gateway); the lab
is who published its weights. That cannot be read off the model id: labs
do not confine themselves to one product line, so a prefix table is
stale the week one of them ships under a new name. The registry's org
namespace is the durable answer, and derivative uploads (quantizations,
fine-tunes) name the repository they came from, so a re-upload points at
its origin instead of claiming the model.
"""

import base64
from dataclasses import dataclass
from typing import Any

import httpx
from sqlmodel import Session, select

from app.core.log import logger
from app.services.ai.models.llm import (
    ROLE_MAKER,
    LargeLanguageModel,
    LLMOrg,
    LLMOrgRole,
)

_SEARCH_URL = "https://huggingface.co/api/models"
_ORG_URL = "https://huggingface.co/api/organizations/{slug}/overview"
_TIMEOUT = 8.0
_CANDIDATES = 5
_MAX_ICON_BYTES = 200_000


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
    icons already speak, so the UI needs no second image path."""
    if not url:
        return None
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Lab avatar fetch failed for {url}: {exc}")
        return None
    if len(response.content) > _MAX_ICON_BYTES:
        return None
    return base64.b64encode(response.content).decode()


async def resolve_lab(model_id: str) -> LabInfo | None:
    """The lab that published a model, or None.

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
            display, avatar_url = slug, None
            org = await client.get(_ORG_URL.format(slug=slug))
            if org.status_code == 200:
                payload = org.json()
                display = str(payload.get("fullname") or slug)
                avatar_url = payload.get("avatarUrl")
            icon_b64 = await _org_avatar(client, avatar_url)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning(f"Lab lookup failed for {model_id}: {exc}")
        return None
    return LabInfo(
        slug=slug,
        name=display,
        homepage=f"https://huggingface.co/{slug}",
        icon_b64=icon_b64,
    )


def _grant_role(session: Session, org: LLMOrg, role: str) -> None:
    """Record a hat this org wears; roles are additive and idempotent."""
    if org.id is None:
        return
    existing = session.exec(
        select(LLMOrgRole).where(LLMOrgRole.org_id == org.id, LLMOrgRole.role == role)
    ).first()
    if existing is None:
        session.add(LLMOrgRole(org_id=org.id, role=role))


async def attach_labs(session: Session, model_ids: list[str]) -> None:
    """Attach each model to the org that published it.

    One registry lookup per model that has no lab yet, so a re-sync
    of an unchanged catalog costs nothing. A model the registry does
    not know keeps a null lab - unmarked beats mislabelled.
    """
    for model_id in model_ids:
        model = session.exec(
            select(LargeLanguageModel).where(LargeLanguageModel.model_id == model_id)
        ).first()
        if model is None or model.made_by_org_id is not None:
            continue
        info = await resolve_lab(model_id)
        if info is None:
            continue
        # The maker may already exist as a SERVING org (OpenAI serves
        # what it builds); that is one row wearing a second hat, not a
        # second row.
        org = session.exec(select(LLMOrg).where(LLMOrg.slug == info.slug)).first()
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
        elif info.icon_b64 and not org.icon_b64:
            org.icon_b64 = info.icon_b64
            session.add(org)
        _grant_role(session, org, ROLE_MAKER)
        model.made_by_org_id = org.id
        session.add(model)
    session.commit()
