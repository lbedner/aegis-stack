"""Where the dashboard may make an operator's change (a restart, a secret).

The dashboard runs inside the webserver, so it calls the API from its own
process at a loopback name (``OWN_API``), wherever the webserver is
reached from: the address the API is asked at says nothing of who is
asking. What does is the address the browser opened the dashboard at
(``page.url``). Its client sends that page as its ``Origin``
(``dashboard_client``), so the API refuses a change from it exactly where
it refuses a browser's (``refusal_at``); ``page_refusal`` says so before
asking, so a control the API would refuse is not offered. Its socket is
the dashboard's own page's (``DashboardOriginMiddleware``).
"""

from typing import Any
from urllib.parse import urlsplit

import flet as ft

from app.core.client import APIClient
from app.core.config import settings
from app.services.shared.deps import refusal_at

OWN_API = f"http://localhost:{settings.PORT}"


def _origin(page: ft.Page) -> str:
    """The page's origin, as a browser names it; ``null`` with none."""
    parts = urlsplit(page.url or "")
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else "null"


def dashboard_client(page: ft.Page, **kwargs: Any) -> APIClient:
    """The session's one API client: its own process, speaking for ``page``."""
    return APIClient(base_url=OWN_API, origin=_origin(page), **kwargs)


def page_refusal(page: ft.Page | None) -> str | None:
    """Why the dashboard on ``page`` may not make an operator's change,
    None when it may; with no page to ask, it may not."""
    return refusal_at((page.url if page is not None else None) or "")
