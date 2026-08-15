"""
Plaid webhook tunnel shutdown hook.

Cancels the discovery task launched by the paired startup hook under
``app/components/backend/startup/``, and drops the runtime webhook URL
that task installed.

Both halves matter. The task polls cloudflared for up to ~20 seconds and
only THEN sets a module-global webhook URL and opens a database session,
so an uncancelled one keeps running long after the app that started it is
gone: it holds a connection open past shutdown, and it rewrites global
state belonging to whatever is running by the time it resolves. Leaving
the URL behind is the same problem a step later, since it points at a
tunnel hostname that dies with the process.

No-op when the startup hook never launched a task, which is every
deployment that is not the dev overlay. Never raises: this is a dev
convenience and must not block the way down (mirrors the payment webhook
forwarder's own shutdown hook).
"""

import asyncio

from app.components.backend.startup import finance_webhook_tunnel as _tunnel
from app.core.log import logger


async def shutdown_finance_webhook_tunnel() -> None:
    """Cancel the tunnel discovery task and clear its webhook override."""
    from app.services.finance.providers.plaid import set_runtime_webhook_url

    task = _tunnel._tunnel_task
    _tunnel._tunnel_task = None

    # Unconditional, and before the await: link tokens read this global,
    # and the hostname it holds dies with this process either way.
    set_runtime_webhook_url(None)

    if task is None or task.done():
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        # Expected: this is the cancellation just requested. Awaiting is
        # what makes the teardown ACTUALLY finished when this returns,
        # rather than merely asked for.
        pass
    except Exception:
        # The task is on its way out regardless; a failure inside it is
        # worth a line but must not block shutdown.
        logger.exception("Plaid webhook tunnel task failed during shutdown")
    logger.info("Plaid webhook tunnel discovery stopped")


shutdown_hook = shutdown_finance_webhook_tunnel
