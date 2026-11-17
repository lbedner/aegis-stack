"""The API providers' logos, for the catalog's provider orgs.

Lab avatars (``lab_resolver``) come from HuggingFace and only reach the
labs behind open-weight models; Anthropic, OpenAI and the rest of the API
providers never get one there. At sync time each provider org without a
mark gets its brand's logo from the provider's homepage, by the shared
fetcher (``app.core.brand_icons``). An org that has a mark keeps it, and a
miss leaves the initial the page already falls back to. A brand whose
homepage wears someone else's mark (llama.cpp's is a GitHub repo) ships its
own instead (``SHIPPED``).
"""

import base64
import functools
from pathlib import Path

from sqlmodel import Session

from app.core.brand_icons import domain_of, fetch_icons
from app.core.log import logger
from app.services.ai.domains.llm.etl import queries
from app.services.ai.models import PROVIDERS, AIProvider
from app.services.ai.models.provider_names import provider_homepage, provider_label

# The mark llama.cpp's own web UI wears (its favicon.svg, as a PNG).
SHIPPED = {AIProvider.LLAMACPP: Path(__file__).parent / "marks" / "llamacpp.png"}


@functools.cache
def _shipped(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


async def attach_provider_marks(session: Session) -> int:
    """Fill the logo of every provider org that lacks one, and write each
    shipped one; how many changed. An org is found by the provider's key
    or its label."""
    domains: dict[str, str] = {}  # org slug -> homepage domain
    shipped: dict[str, Path] = {}  # org slug -> the mark the app ships
    for provider in PROVIDERS:
        slugs = (provider.value, provider_label(provider))
        if provider in SHIPPED:
            shipped.update(dict.fromkeys(slugs, SHIPPED[provider]))
        elif domain := domain_of(provider_homepage(provider)):
            domains.update(dict.fromkeys(slugs, domain))
    orgs = queries.orgs_to_mark(session, domains, shipped)
    wanted = {domains[o.slug] for o in orgs if o.slug in domains}
    icons = await fetch_icons(wanted) if wanted else {}
    filled = 0
    for org in orgs:
        if org.slug in shipped:
            icon: str | None = _shipped(shipped[org.slug])
        else:
            icon = icons.get(domains[org.slug])
        if icon and icon != org.icon_b64:
            org.icon_b64 = icon
            session.add(org)
            filled += 1
    if filled:
        session.commit()
        logger.info(f"Provider marks: {filled} of {len(orgs)} written")
    return filled
