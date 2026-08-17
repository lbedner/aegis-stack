"""Provider connection sync: turn provider links into finance accounts + txns.

Four concerns, one per module - ``plaid_sync`` and ``snaptrade_sync``
for each aggregator's own create/sync/webhook path, ``registry`` for the verbs that
dispatch across both, ``common`` for the connection reads and the
``SyncResult`` shape they all report in.

The per-provider modules never import each other; only ``registry`` knows
both exist. Adding a third aggregator means a new sibling module plus a
branch in ``registry``, and nothing else in the package moves.

The ``_sync`` suffix is load-bearing: ``providers/plaid.py`` and
``providers/snaptrade.py`` next door are the API clients. These modules
are the sync logic that drives them, and the two are easy to confuse from
a filename alone.

Writes but does not commit - the caller owns the transaction.
"""

from app.services.finance.adapters.providers.connections import (
    common,
    plaid_sync,
    registry,
    snaptrade_sync,
)
from app.services.finance.adapters.providers.connections.common import (
    SyncResult,
    get_connection,
    list_plaid_connections,
    list_provider_connections,
)
from app.services.finance.adapters.providers.connections.plaid_sync import (
    complete_hosted_link,
    create_plaid_connection,
    fire_sandbox_webhook,
    process_plaid_webhook,
    refresh_webhook_urls,
    relink_connection,
    sync_plaid_connection,
)
from app.services.finance.adapters.providers.connections.registry import (
    disconnect_connection,
    sync_one_connection,
    sync_owner_connections,
)
from app.services.finance.adapters.providers.connections.snaptrade_sync import (
    complete_snaptrade_connect,
    start_snaptrade_connect,
    sync_snaptrade_connection,
)

__all__ = [
    "SyncResult",
    "common",
    "complete_hosted_link",
    "complete_snaptrade_connect",
    "create_plaid_connection",
    "disconnect_connection",
    "fire_sandbox_webhook",
    "get_connection",
    "list_plaid_connections",
    "list_provider_connections",
    "plaid_sync",
    "process_plaid_webhook",
    "refresh_webhook_urls",
    "registry",
    "relink_connection",
    "snaptrade_sync",
    "start_snaptrade_connect",
    "sync_one_connection",
    "sync_owner_connections",
    "sync_plaid_connection",
    "sync_snaptrade_connection",
]
