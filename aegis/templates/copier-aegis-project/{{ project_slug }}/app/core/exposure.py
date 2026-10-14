"""Whether Overseer may show the app's own source (Code, a route's dry path)
or its data (a table's rows): in dev; elsewhere once an admin turns it on
(a ``Configurable`` flag). With no auth service there is no admin: Overseer
is anyone's to read, so the flag counts only on the build that was never
deployed, and turning it on can never publish the app."""

from app.core.config import settings

LOCAL = "dev"  # BUILD_ID before any deploy stamps it
# The flags, one each: the project's source, and a table's rows.
CODE = "OVERSEER_CODE_ENABLED"
ROWS = "OVERSEER_DATABASE_ROWS_ENABLED"


def deployed() -> bool:
    """Whether this build was deployed (``aegis deploy`` stamped its
    ``BUILD_ID``), rather than run from the project on a laptop."""
    return settings.BUILD_ID != LOCAL


def refusal(flag: str) -> str | None:
    """Why what ``flag`` (``OVERSEER_CODE_ENABLED``) opens is not shown,
    saying what would show it; None when it is."""
    if not (settings.is_dev or bool(getattr(settings, flag, False))):
        return (
            f"outside dev it stays hidden until an admin turns on {flag} in Settings."
        )
    if not settings.AUTH_ENABLED and deployed():
        return (
            "with no one to sign in, a deployed build never shows it: "
            "add auth (aegis add auth) so only admins can."
        )
    return None


def shown(flag: str) -> bool:
    """Whether what ``flag`` opens may be shown (``refusal``)."""
    return refusal(flag) is None
