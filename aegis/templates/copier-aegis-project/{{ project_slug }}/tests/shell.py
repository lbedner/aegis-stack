"""Where the framework's own shell is on this stack: the landing at ``/``,
or, where the project's site owns the root, the Overseer's door. The
tests of the shell (``base.html``) fetch that page, whichever it is."""

from importlib.util import find_spec

from app.core.config import settings

SITE = "app.components.web_frontend.routes.site"


def has_site() -> bool:
    """Whether the project has a public site of its own (and so the root)."""
    return find_spec(SITE) is not None


def shell_path() -> str:
    if not has_site():
        return "/"
    return "/overseer/login" if settings.AUTH_ENABLED else "/overseer"
