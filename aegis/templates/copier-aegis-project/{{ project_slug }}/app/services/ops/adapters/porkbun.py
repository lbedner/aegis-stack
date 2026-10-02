"""Porkbun ``RegistrarAdapter`` — create DNS records + email forwards
on a Porkbun-managed domain.

Porkbun's JSON API auth model is unusual: every request POSTs JSON
with ``apikey`` + ``secretapikey`` fields in the body (no
``Authorization`` header). Endpoints we use:

- ``POST /dns/create/<domain>``               — create a DNS record
- ``POST /dns/retrieve/<domain>``             — list records (for idempotency)
- ``POST /dns/delete/<domain>/<id>``          — delete a record

API keys are scoped per-domain via the API ACCESS toggle inside each
domain's detail page at porkbun.com — strongly recommend enabling that
only for the domain you want this adapter to touch.

Idempotency: ``create_dns_records`` lists existing records first and
no-ops on exact match. Re-running the orchestrator is therefore safe.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

import httpx

from app.core import secrets
from app.services.ops.types import (
    CreatedRecord,
    DnsRecord,
    ForwardingRule,
    RetrievedRecord,
)

logger = logging.getLogger(__name__)

PORKBUN_BASE_URL = "https://api.porkbun.com/api/json/v3"
PORKBUN_TIMEOUT_S = 30.0
PORKBUN_KEYS = ("PORKBUN_API_KEY", "PORKBUN_SECRET_KEY")


# ----------------------------------------------------------------------
# Typed exceptions
# ----------------------------------------------------------------------
#
# Each adapter owns its vendor's exception vocabulary. "HTTP 404" at
# Porkbun has a specific operational meaning depending on the endpoint
# (email forwarding feature off, vs API ACCESS off for the domain),
# and the orchestrator wants to react differently to each — soft-fail
# the optional ones, abort the load-bearing ones. Translating 4xx into
# typed exceptions here keeps the orchestrator readable and avoids
# making it parse URL + status code itself.


class PorkbunError(Exception):
    """Base class for everything this adapter raises that callers care
    about. Generic httpx / RuntimeError errors still bubble up as-is —
    only translated cases derive from this."""


class PorkbunEmailForwardingNotSupportedError(PorkbunError):
    """Porkbun's v3 JSON API has no email-forwarding endpoint at all.

    Email forwarding rules are set up in the Porkbun **web UI** only
    (porkbun.com → domain detail → Email Forwarding). Every
    ``/email/forward/...`` / ``/email/forwarding/...`` URL returns
    404 regardless of whether the feature is enabled or rules
    exist. ``create_email_forward`` raises this immediately so the
    orchestrator can soft-fail with an accurate message instead of
    making a doomed API call and confusing the operator into
    re-enabling something that's already on."""


class PorkbunDomainNotAccessibleError(PorkbunError):
    """``/dns/*`` returned 4xx — most likely the per-domain API ACCESS
    toggle is off at porkbun.com → domain detail → API ACCESS. Could
    also be a typo in the domain or an expired credential.

    This one is load-bearing — DNS records are mandatory for verification
    — so the orchestrator does NOT soft-fail; the error bubbles up to
    the CLI for the operator to fix and retry."""


class PorkbunAdapter:
    """``RegistrarAdapter`` implementation for porkbun.com."""

    name: str = "porkbun"

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        *,
        base_url: str = PORKBUN_BASE_URL,
        timeout_s: float = PORKBUN_TIMEOUT_S,
    ) -> None:
        # Resolved on each call via ``_creds`` (``.env``, then the secrets
        # store), so a key saved while the app runs is used. Constructor
        # overrides win.
        self._api_key_override = api_key
        self._secret_key_override = secret_key
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    # -- Auth helpers -------------------------------------------------------

    async def _creds(self) -> dict[str, str]:
        keys = await secrets.get_many(*PORKBUN_KEYS)
        api_key = self._api_key_override or keys["PORKBUN_API_KEY"]
        secret = self._secret_key_override or keys["PORKBUN_SECRET_KEY"]
        if not api_key or not secret:
            raise RuntimeError(
                "Porkbun credentials missing. Set PORKBUN_API_KEY and "
                "PORKBUN_SECRET_KEY in .env (porkbun.com/account/api), "
                "then enable API ACCESS for the domain you want to touch."
            )
        return {"apikey": api_key, "secretapikey": secret}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON with credentials merged in. Returns the parsed body.

        Porkbun's success responses have ``{"status": "SUCCESS", ...}``;
        most failures have ``{"status": "ERROR", "message": "..."}`` with
        a 200 status code on the HTTP layer (oddly). But some endpoints
        return real 4xx — typically when the underlying feature isn't
        provisioned on the domain (Email Forwarding off, API ACCESS
        off, etc.). Translate those into typed exceptions per-path so
        the orchestrator can react meaningfully instead of catching a
        bare ``httpx.HTTPStatusError`` and parsing URLs.
        """
        body = {**await self._creds(), **payload}
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(url, json=body)

        if resp.status_code in (403, 404):
            self._raise_typed_for_path(path, resp)
            raise RuntimeError("unreachable")

        resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Porkbun {path} returned non-object response: {data!r}")
        return data

    def _raise_typed_for_path(self, path: str, resp: httpx.Response) -> None:
        """Map a 403/404 on a known endpoint family to its typed exception.

        Falls back to the generic ``httpx.HTTPStatusError`` for paths
        outside the email-forward / DNS families, so we don't accidentally
        swallow legitimately-unknown failures behind a vendor-specific
        wrapper.
        """
        if path.startswith("/email/"):
            raise PorkbunEmailForwardingNotSupportedError(
                "Porkbun's API has no email-forwarding endpoint "
                f"(returned {resp.status_code} at {path}). Set up "
                "rules manually at porkbun.com -> domain detail -> "
                "Email Forwarding."
            )
        if path.startswith("/dns/"):
            raise PorkbunDomainNotAccessibleError(
                f"Porkbun returned {resp.status_code} at {path}. Most likely "
                "the per-domain API ACCESS toggle is off (porkbun.com -> "
                "domain detail -> API ACCESS), or the configured credentials "
                "don't have access to this domain."
            )
        resp.raise_for_status()

    # -- DNS records --------------------------------------------------------

    async def create_dns_records(
        self, domain: str, records: list[DnsRecord]
    ) -> list[CreatedRecord]:
        """Create each record on ``domain`` if it doesn't already exist.

        Issues ``/dns/retrieve/<domain>`` once up front so we can skip
        records that match an existing entry exactly. Order in the
        return list matches order in ``records`` so callers can
        correlate by index.
        """
        existing = await self._retrieve_raw(domain)
        existing_index = {_dns_match_key(r): r for r in existing}

        results: list[CreatedRecord] = []
        for spec in records:
            match_key = (
                spec.type.upper(),
                _split_host_from_domain(spec.host, domain).lower(),
                spec.value,
            )
            existing_record = existing_index.get(match_key)
            if existing_record:
                logger.info(
                    "porkbun.adapter: record %s %s already exists; reusing",
                    spec.type,
                    spec.host or "@",
                )
                results.append(
                    CreatedRecord(
                        record=spec,
                        provider_id=str(existing_record.get("id") or ""),
                        created_at=datetime.now(UTC),
                    )
                )
                continue

            host = _split_host_from_domain(spec.host, domain)
            payload: dict[str, Any] = {
                "name": host,
                "type": spec.type.upper(),
                "content": spec.value,
                "ttl": str(max(spec.ttl, 600)),
            }
            if spec.priority is not None:
                payload["prio"] = str(spec.priority)
            data = await self._post(f"/dns/create/{domain}", payload)
            if data.get("status") != "SUCCESS":
                raise RuntimeError(
                    f"Porkbun rejected DNS create for {spec.type} {spec.host} "
                    f"on {domain}: {data.get('message') or data}"
                )
            # Porkbun's quirky duplicate-record response: HTTP 200,
            # status="SUCCESS", but the ``id`` field is a *dict* error
            # blob instead of the usual numeric id.
            raw_id = data.get("id")
            if isinstance(raw_id, dict):
                logger.info(
                    "porkbun.adapter: %s %s already exists on %s; reusing",
                    spec.type,
                    spec.host or "@",
                    domain,
                )
                provider_id = "(existing)"
            else:
                provider_id = str(raw_id or "")
            results.append(
                CreatedRecord(
                    record=spec,
                    provider_id=provider_id,
                    created_at=datetime.now(UTC),
                )
            )
        return results

    async def _retrieve_raw(self, domain: str) -> list[dict[str, Any]]:
        """Return Porkbun's current record list for ``domain`` (or [])."""
        data = await self._post(f"/dns/retrieve/{domain}", {})
        if data.get("status") != "SUCCESS":
            raise RuntimeError(
                f"Porkbun retrieve for {domain} failed: {data.get('message') or data}"
            )
        return list(data.get("records") or [])

    async def list_dns_records(self, domain: str) -> list[RetrievedRecord]:
        """Public, typed view of every record on ``domain``.

        Hosts are normalised to the *relative* form Porkbun's create
        endpoint uses (e.g. ``"app"`` for ``app.example.com``, ``""``
        for apex), so the CLI and tests don't need to know the parent
        domain to compare records.
        """
        records = await self._retrieve_raw(domain)
        out: list[RetrievedRecord] = []
        for r in records:
            try:
                ttl_int = int(r.get("ttl") or 0)
            except (TypeError, ValueError):
                ttl_int = 0
            prio_raw = r.get("prio")
            try:
                prio_int: int | None = int(prio_raw) if prio_raw is not None else None
            except (TypeError, ValueError):
                prio_int = None
            out.append(
                RetrievedRecord(
                    provider_id=str(r.get("id") or ""),
                    host=_split_host_from_domain(str(r.get("name") or ""), domain),
                    type=str(r.get("type") or "").upper(),
                    value=str(r.get("content") or ""),
                    ttl=ttl_int,
                    priority=prio_int,
                )
            )
        return out

    async def delete_dns_record(self, domain: str, provider_id: str) -> None:
        """Remove the record identified by its Porkbun id. Idempotent:
        a 4xx with "record not found" semantics is swallowed.
        """
        if not provider_id:
            raise ValueError("delete_dns_record requires a non-empty provider_id")
        try:
            data = await self._post(f"/dns/delete/{domain}/{provider_id}", {})
        except PorkbunDomainNotAccessibleError:
            raise
        except httpx.HTTPStatusError as exc:
            if 400 <= exc.response.status_code < 500:
                logger.info(
                    "porkbun.adapter: delete %s/%s 4xx; assuming already removed",
                    domain,
                    provider_id,
                )
                return
            raise
        if data.get("status") != "SUCCESS":
            message = str(data.get("message") or "").lower()
            if "not found" in message or "does not exist" in message:
                logger.info(
                    "porkbun.adapter: %s already removed from %s",
                    provider_id,
                    domain,
                )
                return
            raise RuntimeError(
                f"Porkbun rejected DNS delete for {provider_id} on {domain}: "
                f"{data.get('message') or data}"
            )

    # -- Email forwarding ---------------------------------------------------
    #
    # Porkbun's v3 JSON API has no documented endpoint for email
    # forwarding — every path under /email/* returns 404 regardless of
    # whether the feature is enabled or rules exist. Their forwarding
    # is web-UI-only (porkbun.com -> domain detail -> Email Forwarding).
    # We surface this honestly via the typed exception below so the
    # orchestrator soft-fails with an accurate message; we don't make a
    # doomed network call first.

    def supports_email_forwarding(self) -> bool:
        """Capability flag the orchestrator checks before calling
        ``create_email_forward``. Porkbun = False (UI-only)."""
        return False

    async def create_email_forward(
        self, domain: str, local_part: str, target: str
    ) -> ForwardingRule:
        """Always raises — Porkbun has no API for this. Set the rule
        up manually at porkbun.com -> ``{domain}`` -> Email Forwarding."""
        raise PorkbunEmailForwardingNotSupportedError(
            "Porkbun's API has no email-forwarding endpoint. Set up "
            f"{local_part}@{domain} -> {target} manually at "
            f"porkbun.com -> {domain} -> Email Forwarding."
        )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _split_host_from_domain(host: str, registered_domain: str) -> str:
    """Return the **relative** host Porkbun expects in a `name` field.

    Examples (registered_domain = ``example.com``):

    - ``"send"``                       → ``"send"``        (already relative)
    - ``"send.app"``                   → ``"send.app"``    (already relative)
    - ``"send.app.example.com"``       → ``"send.app"``    (trim parent)
    - ``"example.com"``                → ``""``            (apex)
    - ``""`` / ``"@"``                 → ``""``            (apex shorthand)
    """
    h = (host or "").strip()
    if not h or h == "@":
        return ""
    if h.lower() == registered_domain.lower():
        return ""
    suffix = "." + registered_domain.lower()
    if h.lower().endswith(suffix):
        return h[: -len(suffix)]
    return h


def _dns_match_key(record: dict[str, Any]) -> tuple[str, str, str]:
    """Stable key for idempotency comparison against Porkbun records.

    Match on ``(type, relative-name, value)`` so a record with the same
    effective spec is treated as the same. Lowercase normalisation on
    type and name keeps the comparison case-insensitive.
    """
    rtype = str(record.get("type") or "").upper()
    name = str(record.get("name") or "").lower()
    value = str(record.get("content") or "")
    return (rtype, name, value)
