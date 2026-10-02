"""Resend ``MailProviderAdapter`` — add domain, read required DNS
records, poll until verified.

Uses the `resend` Python SDK that's already a dependency for the
auth/email send path. We talk to ``Domains.create`` /
``Domains.list`` / ``Domains.get`` directly because those endpoints
aren't wrapped by ``send_email`` and have their own response shape.

Verification model: Resend returns ``status="not_started"`` until you
explicitly call ``Domains.verify`` (which kicks off the DNS-check
job) and then transitions to ``"pending"`` → ``"verified"`` or
``"failed"``. The poll loop in ``wait_for_verification`` re-issues
``verify`` on first entry to start the job, then polls ``get``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import Any

from app.core import secrets
from app.services.ops.types import (
    DnsRecord,
    DomainAddResult,
    DomainStatus,
)

logger = logging.getLogger(__name__)


class ResendAdapter:
    """``MailProviderAdapter`` implementation for resend.com.

    Each call reads ``RESEND_API_KEY`` through ``app.core.secrets`` (``.env``,
    then the secrets store) and re-sets the SDK's module-level key in case
    another code path (the transactional send path) mutated it. Cheap, and
    keeps adapters re-entrant when callers instantiate per-run.
    """

    name: str = "resend"

    def __init__(self, api_key: str | None = None) -> None:
        # Resolved on each call, so a key saved while the app runs is used.
        self._override_api_key = api_key

    async def _ensure_key(self) -> None:
        import resend  # type: ignore[import-not-found]

        key = self._override_api_key or await secrets.get("RESEND_API_KEY")
        if not key:
            raise RuntimeError(
                "RESEND_API_KEY not set. Add it to .env (sign up at resend.com)."
            )
        resend.api_key = key

    # -- Domain management --------------------------------------------------

    async def add_domain(self, domain: str) -> DomainAddResult:
        """Register ``domain`` with Resend and return the DNS records the
        registrar needs to add.

        Idempotent. Strategy is list-first: if the domain already exists
        we reuse it (cheap GET to ``Domains.get`` for the records), and
        only call ``Domains.create`` for genuinely-new domains. This
        avoids using ResendError as control flow — Resend phrases the
        duplicate signal differently across versions, so string-matching
        on the exception was brittle.
        """
        await self._ensure_key()
        import resend  # type: ignore[import-not-found]

        existing = await self._find_existing_domain_or_none(domain)
        if existing is not None:
            logger.info("resend.adapter: domain %s already registered; reusing", domain)
            return _to_domain_add_result(domain, existing)

        created = await asyncio.to_thread(resend.Domains.create, {"name": domain})
        return _to_domain_add_result(domain, created)

    async def get_domain_status(self, domain: str) -> DomainStatus:
        """Resolve domain by name → fetch fresh status."""
        await self._ensure_key()
        info = await self._find_existing_domain(domain)
        return _to_domain_status(domain, info)

    async def wait_for_verification(
        self, domain: str, *, timeout_s: int = 600, poll_interval_s: int = 5
    ) -> DomainStatus:
        """Poll Resend until the domain reports ``verified`` (or timeout).

        Kicks off verification once on entry; Resend caches the result
        of subsequent ``verify`` calls so re-issuing inside the loop is
        a no-op. Returns the final ``DomainStatus`` regardless of
        outcome — caller checks ``.verified``.
        """
        await self._ensure_key()
        import resend  # type: ignore[import-not-found]

        info = await self._find_existing_domain(domain)
        domain_id = info.get("id")
        if not domain_id:
            raise RuntimeError(
                f"Resend returned no id for domain {domain!r}; cannot poll."
            )

        try:
            await asyncio.to_thread(resend.Domains.verify, domain_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resend.adapter: verify kickoff for %s raised %s; continuing to poll",
                domain,
                exc,
            )

        deadline = datetime.now(UTC).timestamp() + max(timeout_s, 1)
        while True:
            fresh = await asyncio.to_thread(resend.Domains.get, domain_id)
            status = _to_domain_status(domain, fresh)
            if status.verified or status.status == "failed":
                return status
            if datetime.now(UTC).timestamp() >= deadline:
                return status
            await asyncio.sleep(max(poll_interval_s, 1))

    # -- Internals ----------------------------------------------------------

    async def _find_existing_domain_or_none(self, domain: str) -> dict[str, Any] | None:
        """Return the Resend ``Domains.get`` shape for ``domain``, or None.

        ``Domains.list`` gives us the id; ``Domains.get`` gives us the
        DNS-record list (the list endpoint doesn't include it). Returns
        None for not-found so the caller can branch instead of catching.
        """
        import resend  # type: ignore[import-not-found]

        listing = await asyncio.to_thread(resend.Domains.list)
        items = listing.get("data", listing) if isinstance(listing, dict) else listing
        match = next(
            (d for d in items if (d.get("name") or "").lower() == domain.lower()),
            None,
        )
        if not match:
            return None
        return await asyncio.to_thread(resend.Domains.get, match["id"])

    async def _find_existing_domain(self, domain: str) -> dict[str, Any]:
        """Strict variant: raises if the domain isn't registered yet."""
        result = await self._find_existing_domain_or_none(domain)
        if result is None:
            raise RuntimeError(
                f"Resend has no domain {domain!r} — call add_domain first."
            )
        return result


# ----------------------------------------------------------------------
# Response shape normalisation
# ----------------------------------------------------------------------


def _to_domain_add_result(domain: str, raw: dict[str, Any]) -> DomainAddResult:
    """Map a Resend create/get payload to ``DomainAddResult``.

    Resend's record payload looks like::

        {
          "id": "...",
          "name": "app.example.com",
          "status": "not_started",
          "records": [
            {"record": "SPF",   "name": "send",              "type": "TXT", ...},
            {"record": "DKIM",  "name": "resend._domainkey", "type": "TXT", ...},
            {"record": "MX",    "name": "send",              "type": "MX",  ...},
            ...
          ]
        }
    """
    records_raw = raw.get("records") or []
    required: list[DnsRecord] = []
    for r in records_raw:
        ttl_raw = r.get("ttl")
        try:
            ttl = int(ttl_raw) if ttl_raw and str(ttl_raw).isdigit() else 3600
        except (TypeError, ValueError):
            ttl = 3600
        priority_raw = r.get("priority")
        try:
            priority = int(priority_raw) if priority_raw is not None else None
        except (TypeError, ValueError):
            priority = None
        required.append(
            DnsRecord(
                host=str(r.get("name") or ""),
                type=str(r.get("type") or "TXT").upper(),
                value=str(r.get("value") or ""),
                ttl=ttl,
                priority=priority,
            )
        )
    return DomainAddResult(
        domain=domain,
        required_records=required,
        provider_domain_id=str(raw.get("id") or ""),
        raw=raw,
    )


def _to_domain_status(domain: str, raw: dict[str, Any]) -> DomainStatus:
    status = str(raw.get("status") or "unknown").lower()
    return DomainStatus(
        domain=domain,
        verified=status == "verified",
        status=status,
        last_checked_at=datetime.now(UTC),
        raw=raw,
    )
