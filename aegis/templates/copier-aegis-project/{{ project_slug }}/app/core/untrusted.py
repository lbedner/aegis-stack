"""A file someone uploaded, served back from this app's own origin.

Shown inline as the type it came with, an SVG's or an HTML file's script
would run as this app, with the viewer's session. Served through here it
runs nothing and loads nothing, and the browser never takes it for another
type. A PDF is the one left out: the browser's viewer runs it in its own
sandbox, and a sandboxed page cannot open that viewer.
"""

from starlette.responses import Response

NO_SNIFFING = {"X-Content-Type-Options": "nosniff"}
INERT = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"
}
VIEWED_ELSEWHERE = frozenset({"application/pdf"})


def untrusted_response(
    data: bytes, media_type: str, headers: dict[str, str] | None = None
) -> Response:
    """``data`` as ``media_type``, inert whatever is in it."""
    kept = NO_SNIFFING if media_type in VIEWED_ELSEWHERE else NO_SNIFFING | INERT
    return Response(data, media_type=media_type, headers=kept | (headers or {}))
