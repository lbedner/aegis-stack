"""Server-sent events: line parsing and the streaming POST helper.

Lives beside (not inside) the API client so the client stays a plain
request/response surface; anything that consumes an SSE endpoint routes
through here, still riding the client's cookie-carrying transport.
"""

from collections.abc import AsyncIterator
import json
from typing import TYPE_CHECKING, Any

import httpx

from app.core.log import logger

if TYPE_CHECKING:
    from app.core.client import APIClient


async def parse_sse_lines(
    lines: AsyncIterator[str], *, source: str = "sse"
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Turn ``event:`` / ``data:`` line pairs into ``(event, payload)`` tuples.

    Payloads must be JSON objects; a malformed line is logged and skipped
    rather than ending the stream, since one bad frame should not kill a
    long-lived chat turn.
    """
    event_name = "message"
    async for line in lines:
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload:
            continue
        try:
            yield event_name, json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("sse.bad_payload", source=source)


async def stream_sse_post(
    client: "APIClient",
    endpoint: str,
    json_body: dict[str, Any] | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """POST through the API client and yield SSE ``(event, payload)`` pairs.

    Chat streams are open-ended, so the read timeout is disabled; the
    server closing the stream ends iteration. Transport errors set the
    client's ``last_error`` and end the stream rather than raising,
    matching the client's returns-None-on-error contract.
    """
    client.last_error = None
    try:
        async with client.stream(
            "POST",
            endpoint,
            json=json_body,
            timeout=httpx.Timeout(client.timeout, read=None),
        ) as response:
            if response.status_code >= 400:
                client.last_error = f"HTTP {response.status_code}"
                return
            async for pair in parse_sse_lines(
                response.aiter_lines(), source=endpoint
            ):
                yield pair
    except httpx.HTTPError as exc:
        client.last_error = str(exc)
        logger.warning(
            "sse.transport_error", endpoint=endpoint, error=str(exc)
        )
