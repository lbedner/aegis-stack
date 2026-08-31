"""Browser-upload plumbing shared by every FilePicker flow.

One signer for the dashboard-mounted flet upload endpoint, used by the
register's file imports and chat's image attachments alike.
"""

from __future__ import annotations

from app.core.config import settings


def signed_upload_url(server_name: str, *, expires_seconds: int = 600) -> str:
    """Signed URL for the dashboard-mounted flet upload endpoint.

    ``page.get_upload_url`` cannot be used here: the Flet app is mounted
    at ``/dashboard``, so flet would sign its sub-app-relative endpoint
    while the server verifies the externally visible path
    (``request.url.path`` includes the mount prefix). Signing the
    external path directly satisfies both the route and the check.
    """
    from flet_web.uploads import build_upload_url

    return build_upload_url(
        "/dashboard/upload", server_name, expires_seconds, settings.SECRET_KEY
    )
