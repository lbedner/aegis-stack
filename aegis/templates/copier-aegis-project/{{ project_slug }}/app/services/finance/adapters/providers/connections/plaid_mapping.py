"""Plaid payload -> our field names. Pure functions, no I/O.

The counterpart to ``snaptrade_mapping``: the place a provider's own
enrichment is translated into the neutral fields the ledger understands,
so ``plaid_sync`` stays the story of what syncing DOES rather than of
what Plaid's JSON looks like.
"""

from __future__ import annotations

from typing import Any


def merchant_logo(txn: dict[str, Any]) -> str | None:
    """The merchant logo Plaid attached to a transaction, as the one
    provider-neutral ``logo_url`` the ledger understands.

    Plaid carries it at the top level and again on the merchant
    counterparty; either will do, and a payee takes it on attribution
    (``domains/ledger/merchants.py``).
    """
    if txn.get("logo_url"):
        return str(txn["logo_url"])
    for party in txn.get("counterparties") or []:
        if party.get("type") == "merchant" and party.get("logo_url"):
            return str(party["logo_url"])
    return None
