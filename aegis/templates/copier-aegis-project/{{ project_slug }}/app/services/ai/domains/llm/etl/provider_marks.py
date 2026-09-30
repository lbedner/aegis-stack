"""The API providers' logos, for the catalog's provider orgs.

Lab avatars (``lab_resolver``) come from HuggingFace and only reach the
labs behind open-weight models; Anthropic, OpenAI and the rest of the API
providers never get one there. At sync time each provider org without a
mark gets its brand's logo from the provider's homepage, by the shared
fetcher (``app.core.brand_icons``). An org that has a mark keeps it, and a
miss leaves the initial the page already falls back to.
"""

from sqlmodel import Session

from app.core.brand_icons import domain_of, fetch_icons
from app.core.log import logger
from app.services.ai.domains.llm.etl import queries
from app.services.ai.models import PROVIDERS
from app.services.ai.models.provider_names import provider_homepage, provider_label


async def attach_provider_marks(session: Session) -> int:
    """Fill the logo of every provider org that lacks one; how many were
    filled. An org is found by the provider's key or its label."""
    domains: dict[str, str] = {}  # org slug -> homepage domain
    for provider in PROVIDERS:
        domain = domain_of(provider_homepage(provider))
        if domain:
            for slug in (provider.value, provider_label(provider)):
                domains[slug] = domain
    orgs = queries.orgs_without_marks(session, domains)
    if not orgs:
        return 0
    icons = await fetch_icons({domains[o.slug] for o in orgs})
    filled = 0
    for org in orgs:
        icon = icons.get(domains[org.slug])
        if icon:
            org.icon_b64 = icon
            session.add(org)
            filled += 1
    session.commit()
    logger.info(f"Provider marks: {filled} of {len(orgs)} filled")
    return filled
