"""SnapTrade connections: register the user, adopt brokerages, sync them.

A package rather than one module, mirroring ``plaid_sync`` because it
does the same job for the other provider:

- ``accounts``    the brokerage accounts SnapTrade reports
- ``investments`` positions and date-windowed activities
- ``sync``        one pass over a connection, and the credential helpers
- ``lifecycle``   registering the user and adopting authorizations

Everything lands in the same tables Plaid writes, through the same
shared upsert helpers (``upsert_provider_security`` merges
cross-provider duplicates by FIGI/CUSIP/ISIN).

Writes but does not commit - the caller owns the transaction.
"""

from app.services.finance.adapters.providers.connections.snaptrade_sync.lifecycle import (
    complete_snaptrade_connect,
    start_snaptrade_connect,
)
from app.services.finance.adapters.providers.connections.snaptrade_sync.sync import (
    # ``registry._revoke_snaptrade`` reaches for this through the module,
    # as it did when this was one file. Re-exported rather than promoted:
    # a refactor should not widen an API. That a sibling reads another
    # module's private is worth fixing, but not in this commit.
    _snaptrade_user_id as _snaptrade_user_id,
)
from app.services.finance.adapters.providers.connections.snaptrade_sync.sync import (
    sync_snaptrade_connection,
)

__all__ = [
    "complete_snaptrade_connect",
    "start_snaptrade_connect",
    "sync_snaptrade_connection",
]
