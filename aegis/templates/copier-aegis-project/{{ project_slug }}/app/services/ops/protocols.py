"""Protocol shapes for ops adapters.

Two protocols, one per concern — explicitly NOT a flattened
``OperationsAdapter`` umbrella, because DNS-side semantics and
mail-side semantics share almost nothing. Keeping them separate makes
the abstractions tighter and lets future ops concerns (SSL, storage,
hosting, DB) define their own protocols without bending these.

These are ``typing.Protocol`` shapes (structural, not nominal) so an
adapter doesn't have to ``inherit`` — it just has to implement the
methods. Easier to evolve and easier to mock in tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.services.ops.types import (
    CreatedRecord,
    DnsRecord,
    DomainAddResult,
    DomainStatus,
    ForwardingRule,
    RetrievedRecord,
)


@runtime_checkable
class RegistrarAdapter(Protocol):
    """Provisions DNS records and (optionally) email forwarding rules
    against a domain the user already owns at the registrar.

    Adapters MUST be idempotent: calling ``create_dns_records`` twice
    with the same input MUST NOT create duplicates. The mail-provider
    side re-asks for verification on each run, so a partial run that
    crashes after some records went in should be safe to replay.
    """

    name: str

    async def create_dns_records(
        self, domain: str, records: list[DnsRecord]
    ) -> list[CreatedRecord]:
        """Create (or no-op-confirm) each record. Returns one row per
        spec in the same order so callers can correlate input -> result."""
        ...

    async def list_dns_records(self, domain: str) -> list[RetrievedRecord]:
        """Return every record currently on ``domain``. Hosts are returned
        as the relative form (``"app"``, not ``"app.example.com"``) so
        callers don't need to know the parent domain to compare."""
        ...

    async def edit_dns_record(
        self, domain: str, provider_id: str, record: DnsRecord
    ) -> None:
        """Replace the fields of a record by its registrar-issued id; it
        keeps that id."""
        ...

    async def delete_dns_record(self, domain: str, provider_id: str) -> None:
        """Remove a single record by its registrar-issued id. No-ops (does
        not raise) if the id is already gone — same idempotency contract
        as ``create_dns_records``."""
        ...

    async def create_email_forward(
        self, domain: str, local_part: str, target: str
    ) -> ForwardingRule:
        """Forward ``local_part@domain`` -> ``target``. Idempotent."""
        ...


@runtime_checkable
class MailProviderAdapter(Protocol):
    """Manages domains at a transactional-email provider (Resend,
    Postmark, SendGrid, ...). Tells the orchestrator which DNS records
    the registrar needs to add and polls for verification afterwards.
    """

    name: str

    async def add_domain(self, domain: str) -> DomainAddResult:
        """Register the domain with the provider and return the DNS
        records the registrar needs to create. Idempotent — calling
        twice on the same domain returns the existing record set."""
        ...

    async def get_domain_status(self, domain: str) -> DomainStatus:
        """One status snapshot. Used by ``wait_for_verification`` and
        by ad-hoc inspection from the CLI."""
        ...

    async def wait_for_verification(
        self, domain: str, *, timeout_s: int = 600, poll_interval_s: int = 5
    ) -> DomainStatus:
        """Block (asynchronously) until the domain reports ``verified``
        or until ``timeout_s`` elapses. Returns the final status either
        way — caller checks ``status.verified``."""
        ...
