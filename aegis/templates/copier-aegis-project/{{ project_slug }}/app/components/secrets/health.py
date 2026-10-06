"""Health check for the secrets component (dashboard ComponentStatus).

Healthy when the store is installed: how many declared credentials are
set, and how many of those are stored here rather than in ``.env``. A
warning, with the reason, when it cannot be (no ``ENCRYPTION_KEY``) or when
a key something enabled needs is missing; optional keys never warn.
"""

from app.core import secrets
from app.core.config import settings
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus, ComponentStatusType

from .store import NO_KEY


async def check_secrets_health() -> ComponentStatus:
    """Set and stored counts, or why nothing can be stored."""
    if not getattr(settings, "ENCRYPTION_KEY", None):
        return ComponentStatus(
            name=ComponentName.SECRETS,
            status=ComponentStatusType.WARNING,
            message=NO_KEY,
            metadata={"backend": "database", "writable": False},
        )
    rows = await secrets.status()
    is_set = [row for row in rows if row.is_set]
    stored = [row for row in is_set if row.source not in (None, secrets.ENV)]
    needed = [row for row in rows if row.needed]
    missing = [row.name for row in needed if not row.is_set]
    return ComponentStatus(
        name=ComponentName.SECRETS,
        status=ComponentStatusType.WARNING if missing else ComponentStatusType.HEALTHY,
        message=(
            f"Needed and not set: {', '.join(missing)}"
            if missing
            else f"{len(is_set)} of {len(rows)} set, {len(stored)} stored here"
        ),
        metadata={
            "backend": "database",
            "writable": secrets.writable(),
            "declared": len(rows),
            "set": len(is_set),
            "stored": len(stored),
            "needed": len(needed),
            "needed_set": len(needed) - len(missing),
        },
    )
