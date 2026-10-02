"""The one HTTP seam for provider and DNS APIs.

Clients take a ``Requester`` instead of opening connections themselves, so
tests swap in a fake and nothing ever reaches a real cloud account.
"""

import json
from collections.abc import Callable
from typing import Any, Protocol

import urllib3

Requester = Callable[..., dict[str, Any]]


class ProvisionError(Exception):
    """A provider or DNS call failed; ``status`` is the HTTP status when known."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _Pool(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


def mask_token(token: str) -> str:
    """The most of a token that may ever be shown: its last four characters."""
    return f"...{token[-4:]}"


def _error_message(data: dict[str, Any]) -> str:
    """Pull the message out of a Hetzner or Cloudflare error body."""
    error = data.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    errors = data.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("message", ""))
    return ""


def json_requester(base_url: str, token: str, pool: _Pool | None = None) -> Requester:
    """A ``request(method, path, body=None) -> dict`` bound to one API and token.

    The token only ever travels in the Authorization header; error messages
    carry the method, path, status and the API's own message, never the token.
    """
    http = pool or urllib3.PoolManager(timeout=urllib3.Timeout(total=30), retries=False)

    def request(
        method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = http.request(
            method,
            f"{base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        try:
            data = json.loads(response.data) if response.data else {}
        except ValueError:
            data = {}
        if response.status >= 400:
            detail = _error_message(data) or "no error message"
            raise ProvisionError(
                f"{method} {path}: HTTP {response.status}: {detail}",
                status=response.status,
            )
        return data

    return request
