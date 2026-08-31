"""Injects the paste-capture script into the dashboard page.

Flet exposes no OS-clipboard image API (text only), so pasting a
screenshot has to be caught in the browser itself: this middleware
splices an inline listener into the dashboard's HTML that posts pasted
image files to the generic ``/api/v1/pastebox`` endpoint, where
consumer surfaces drain them (see ``app/core/pastebox.py``).

Injection over a vendored index.html on purpose: Flet's index markup
changes across versions, and a response-time splice keeps working
without carrying a copy of it.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Posts every pasted image file; non-file pastes (plain text) fall
# through untouched so normal text paste keeps working.
_PASTE_SCRIPT = b"""<script>
document.addEventListener("paste", function (event) {
  var items = (event.clipboardData || {}).files || [];
  for (var i = 0; i < items.length; i++) {
    var file = items[i];
    if (!file.type || file.type.indexOf("image/") !== 0) continue;
    var form = new FormData();
    form.append("file", file, file.name || "pasted-image.png");
    fetch("/api/v1/pastebox/incoming", { method: "POST" }).finally(function () {
      fetch("/api/v1/pastebox", { method: "POST", body: form });
    });
  }
});
</script>"""


def inject_paste_script(body: bytes) -> bytes:
    """The pure splice: script before ``</head>``, or the body untouched
    when there is no head to splice into (non-HTML payloads)."""
    marker = b"</head>"
    if marker not in body:
        return body
    return body.replace(marker, _PASTE_SCRIPT + marker, 1)


class PasteCaptureMiddleware:
    """Buffers dashboard HTML responses and splices the capture script.

    Pure ASGI (not ``BaseHTTPMiddleware``): the dashboard index is one
    small document, and buffering only happens for ``text/html`` under
    the dashboard mount - every other response streams through as-is.
    """

    def __init__(self, app: ASGIApp, mount_path: str = "/dashboard") -> None:
        self.app = app
        self.mount_path = mount_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.mount_path):
            await self.app(scope, receive, send)
            return

        start_message: Message | None = None
        chunks: list[bytes] = []
        is_html = False

        async def buffered_send(message: Message) -> None:
            nonlocal start_message, is_html
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers") or [])
                is_html = b"text/html" in headers.get(b"content-type", b"")
                if not is_html:
                    await send(message)
                    return
                start_message = message
                return
            if message["type"] == "http.response.body" and is_html:
                chunks.append(message.get("body") or b"")
                if not message.get("more_body"):
                    body = inject_paste_script(b"".join(chunks))
                    assert start_message is not None
                    start_message["headers"] = [
                        (k, v)
                        for k, v in start_message["headers"]
                        if k.lower() != b"content-length"
                    ] + [(b"content-length", str(len(body)).encode())]
                    await send(start_message)
                    await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, buffered_send)
