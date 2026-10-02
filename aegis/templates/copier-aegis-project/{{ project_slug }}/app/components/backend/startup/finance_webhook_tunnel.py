"""
Plaid webhook tunnel startup hook.

The dev compose overlay runs a cloudflared quick-tunnel sidecar
(``plaid-tunnel``) that exposes the backend on a random public
``*.trycloudflare.com`` hostname and sets ``PLAID_TUNNEL_METRICS_URL``.
This hook discovers that hostname from the sidecar's ``/quicktunnel``
metrics endpoint, then:

1. Overrides the webhook URL new link tokens carry
   (``set_runtime_webhook_url``), and
2. Reconciles every existing Plaid Item via ``/item/webhook/update`` —
   the hostname rotates on every ``docker compose up``, so without this
   step old Items would deliver webhooks to a dead tunnel.

Gates — a no-op with a single log line unless ALL of:

1. ``PLAID_TUNNEL_METRICS_URL`` is set (the overlay sets it; prod and
   plain compose don't).
2. ``PLAID_CLIENT_ID`` is set: ``make serve`` only starts the tunnel with
   Plaid credentials, so without them there is nothing to discover.
3. The tunnel answers within the discovery window (cloudflared may still
   be provisioning when the backend boots, so discovery retries).

Only ``PLAID_WEBHOOK_PATH`` answers through the tunnel: the tunnel guard
middleware refuses everything else, because the app has no login.

Runs as a fire-and-forget task so a slow tunnel never delays startup,
and never raises — this is a dev convenience, it must degrade silently
(mirrors the payment webhook forwarder hook).
"""

import asyncio
from typing import Any

import httpx

from app.core import secrets
from app.core.config import settings
from app.core.log import logger

# The tunnel sidecar usually answers within ~2s of boot; the backend and
# sidecar start concurrently, so poll briefly before giving up.
_DISCOVERY_ATTEMPTS = 10
_DISCOVERY_INTERVAL_SECONDS = 2.0

# The one route the tunnel exists for, and the only one it lets through.
PLAID_WEBHOOK_PATH = "/api/v1/finance/webhook/plaid"

# Module-level so the task isn't garbage-collected mid-flight.
_tunnel_task: asyncio.Task[None] | None = None


def tunnel_metrics_url() -> str | None:
    """Where the dev overlay's tunnel reports its hostname, or None.

    ``getattr``: a finance stack without Plaid has no such setting at all.
    """
    return getattr(settings, "PLAID_TUNNEL_METRICS_URL", None)


async def discover_tunnel_hostname(metrics_url: str) -> str | None:
    """The quick tunnel's public hostname from cloudflared's metrics server.

    ``GET {metrics_url}/quicktunnel`` returns ``{"hostname": "..."}`` once the
    tunnel is provisioned. Returns None while unreachable or unprovisioned.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{metrics_url}/quicktunnel")
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    hostname = data.get("hostname")
    return hostname or None


async def _discover_and_reconcile(metrics_url: str) -> None:
    from app.services.finance.adapters.providers import connections
    from app.services.finance.adapters.providers.plaid import set_runtime_webhook_url

    hostname: str | None = None
    for _ in range(_DISCOVERY_ATTEMPTS):
        hostname = await discover_tunnel_hostname(metrics_url)
        if hostname:
            break
        await asyncio.sleep(_DISCOVERY_INTERVAL_SECONDS)
    if not hostname:
        logger.warning(
            "Plaid webhook tunnel not reachable at %s; webhooks stay on "
            "PLAID_WEBHOOK_URL (real-time nudges off, sync still works).",
            metrics_url,
        )
        return

    webhook_url = f"https://{hostname}{PLAID_WEBHOOK_PATH}"
    set_runtime_webhook_url(webhook_url)
    logger.info("Plaid webhooks routed through tunnel: %s", webhook_url)

    from app.core.db import get_async_session

    try:
        async with get_async_session() as session:
            updated = await connections.refresh_webhook_urls(
                session, webhook_url=webhook_url
            )
            await session.commit()
    except Exception:
        logger.exception("Plaid webhook URL reconciliation failed")
        return
    if updated:
        logger.info("Repointed %d Plaid item(s) at the tunnel URL", updated)


async def startup_finance_webhook_tunnel() -> None:
    global _tunnel_task
    metrics_url = tunnel_metrics_url()
    if not metrics_url or not await secrets.get("PLAID_CLIENT_ID"):
        logger.debug("Plaid webhook tunnel not configured; skipping")
        return
    _tunnel_task = asyncio.get_running_loop().create_task(
        _discover_and_reconcile(metrics_url)
    )


# Export hook(s) for auto-discovery by ``app/components/backend/hooks.py``.
startup_hook: Any = startup_finance_webhook_tunnel
