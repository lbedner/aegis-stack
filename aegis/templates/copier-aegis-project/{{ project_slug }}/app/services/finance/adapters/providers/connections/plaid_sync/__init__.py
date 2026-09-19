"""Plaid connections: create one, sync it, and answer its webhooks.

A package rather than one module, split by what Plaid itself returns:

- ``accounts``      the account rows and their liability detail
- ``transactions``  the cursor-based sync lane, and removals
- ``investments``   securities, trades and holdings
- ``sync``          one pass over a connection, in dependency order
- ``lifecycle``     create, re-link, and the webhook handlers

Writes but does not commit - the caller owns the transaction. The
mapping tables live in ``plaid_mapping`` so this stays the story of
what syncing DOES.
"""

from app.services.finance.adapters.providers.connections.plaid_sync.lifecycle import (
    complete_hosted_link,
    create_plaid_connection,
    fire_sandbox_webhook,
    process_plaid_webhook,
    refresh_webhook_urls,
    relink_connection,
)
from app.services.finance.adapters.providers.connections.plaid_sync.sync import (
    sync_plaid_connection,
)

__all__ = [
    "complete_hosted_link",
    "create_plaid_connection",
    "fire_sandbox_webhook",
    "process_plaid_webhook",
    "refresh_webhook_urls",
    "relink_connection",
    "sync_plaid_connection",
]
