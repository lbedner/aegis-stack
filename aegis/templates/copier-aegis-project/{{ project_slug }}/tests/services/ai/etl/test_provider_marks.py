"""Each provider's org wears its brand's logo: filled at sync time from the
provider's homepage by the shared fetcher (``app.core.brand_icons``), once,
and only where the org has none. Lab avatars cover open-weight models;
this covers the API providers they never reach."""

from typing import Any

import pytest
from sqlmodel import Session, select

from app.services.ai.domains.llm.etl import provider_marks
from app.services.ai.models.llm import LLMOrg


async def test_a_provider_org_without_a_mark_gets_one(
    etl_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    etl_session.add(LLMOrg(slug="anthropic", name="Anthropic"))
    etl_session.add(LLMOrg(slug="openai", name="OpenAI", icon_b64="already"))
    etl_session.commit()
    asked: list[list[str]] = []

    async def fetch(domains: Any) -> dict[str, str | None]:
        asked.append(sorted(domains))
        return dict.fromkeys(domains, "logo")

    monkeypatch.setattr(provider_marks, "fetch_icons", fetch)
    filled = await provider_marks.attach_provider_marks(etl_session)
    orgs = {o.slug: o for o in etl_session.exec(select(LLMOrg)).all()}
    assert orgs["anthropic"].icon_b64 == "logo"
    assert orgs["openai"].icon_b64 == "already"
    assert asked == [["anthropic.com"]] and filled == 1


async def test_a_miss_leaves_the_initial(
    etl_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    etl_session.add(LLMOrg(slug="groq", name="groq"))
    etl_session.commit()

    async def fetch(domains: Any) -> dict[str, str | None]:
        return dict.fromkeys(domains)

    monkeypatch.setattr(provider_marks, "fetch_icons", fetch)
    assert await provider_marks.attach_provider_marks(etl_session) == 0
    org = etl_session.exec(select(LLMOrg).where(LLMOrg.slug == "groq")).one()
    assert org.icon_b64 is None


def test_every_provider_has_a_homepage() -> None:
    from app.services.ai.models import PROVIDERS
    from app.services.ai.models.provider_names import provider_homepage

    assert all(provider_homepage(p) for p in PROVIDERS)
