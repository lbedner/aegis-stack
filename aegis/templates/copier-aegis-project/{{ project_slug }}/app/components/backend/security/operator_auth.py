"""The gate on the operator's paths: the API docs (``/docs``, ``/redoc``,
``/openapi.json``) and the detailed health tree (``/health/detailed``),
which describes every component, its versions and tables.

Unset ``DOCS_USERNAME``/``DOCS_PASSWORD``: open in dev, 404 elsewhere
(fail-closed). Set: HTTP Basic, compared in constant time. A caller over
loopback needs neither: the CLI's ``health``, ``live_status`` and the
dashboard ask the webserver from inside its container, and Traefik or a
published port never arrives as loopback. Behind Traefik these paths are
also IP-restricted (``ADMIN_IP_ALLOWLIST``).
"""

import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import settings

LOOPBACK = frozenset({"127.0.0.1", "::1"})

_basic = HTTPBasic(auto_error=False)


def require_operator(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> None:
    if request.client is not None and request.client.host in LOOPBACK:
        return
    expected_user = settings.DOCS_USERNAME
    expected_pass = settings.DOCS_PASSWORD
    if not expected_user or not expected_pass:
        if settings.APP_ENV == "dev":
            return
        raise HTTPException(status_code=404)
    if credentials is None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    pass_ok = secrets.compare_digest(credentials.password, expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
