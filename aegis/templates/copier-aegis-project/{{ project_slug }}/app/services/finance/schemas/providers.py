"""Plaid/SnapTrade provider handshake shapes.

A topic module of the ``schemas`` package; every name here is
re-exported from the package root, which stays the one import path.
Money fields are integer minor units (cents); the frontend formats them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    pass


class LinkTokenResponse(BaseModel):
    """A Plaid Link token the frontend hands to Plaid Link."""

    link_token: str


class PlaidExchangeRequest(BaseModel):
    """POST body for /plaid/exchange — the public token from Plaid Link."""

    public_token: str
    label: str | None = None


class SyncResultResponse(BaseModel):
    """Outcome of a connection sync."""

    connection_id: int
    accounts: int
    added: int
    updated: int
    removed: int
    holdings: int = 0
    trades: int = 0


class SyncSummaryResponse(BaseModel):
    """Aggregate outcome of syncing every connection for the caller."""

    connections: int
    results: list[SyncResultResponse]


class HostedLinkResponse(BaseModel):
    """A Plaid Hosted Link session — open the URL, poll with the token."""

    hosted_link_url: str
    link_token: str


class HostedLinkCompleteRequest(BaseModel):
    """POST body for /plaid/hosted-link/complete."""

    link_token: str


class SnapTradeConnectResponse(BaseModel):
    """A SnapTrade connection-portal session — open the URL in a new tab
    (expires in ~5 minutes) and poll ``/snaptrade/connect/complete``."""

    redirect_uri: str
    connection_id: int


class WebhookAckResult(BaseModel):
    """What a verified inbound provider webhook did, for the provider's own
    delivery log - never a client-facing payload."""

    status: str
