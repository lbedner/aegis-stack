"""Plaid API client — a thin async httpx wrapper over the endpoints the finance
service uses. No SDK dependency; verified against the sandbox.

Endpoints: ``link/token/create``, ``item/public_token/exchange``,
``accounts/get``, ``transactions/sync`` (cursor-paged), plus the
``sandbox/public_token/create`` shortcut used by the sandbox-connect flow.

Sign convention: Plaid amounts are POSITIVE for money leaving the account
(outflow). The sync layer negates them to this project's convention where a
negative amount is an outflow.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.core.config import settings

# A webhook JWT older than this is replayable and gets rejected (Plaid's
# documented verification window).
_WEBHOOK_MAX_AGE_SECONDS = 5 * 60

_ENV_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidError(RuntimeError):
    """A Plaid API error (``error_code`` carries the machine-readable reason)."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(f"{error_code}: {message}")


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode())


def _webhook_error(reason: str) -> PlaidError:
    return PlaidError("invalid_webhook", reason)


# Dev-tunnel override for the webhook delivery URL. The startup hook
# (``app/components/backend/startup/finance_webhook_tunnel.py``) sets this
# after discovering the cloudflared quick tunnel's public hostname; when unset,
# the static ``settings.PLAID_WEBHOOK_URL`` applies.
_runtime_webhook_url: str | None = None


def set_runtime_webhook_url(url: str | None) -> None:
    global _runtime_webhook_url
    _runtime_webhook_url = url


def get_webhook_url() -> str | None:
    """The webhook URL new link tokens carry: tunnel override, else settings."""
    return _runtime_webhook_url or settings.PLAID_WEBHOOK_URL


class PlaidClient:
    """Async Plaid client. Reads credentials/environment from settings unless
    overridden (handy for tests)."""

    def __init__(
        self,
        *,
        client_id: str | None = None,
        secret: str | None = None,
        environment: str | None = None,
    ) -> None:
        self._client_id = client_id or settings.PLAID_CLIENT_ID
        self._secret = secret or settings.PLAID_SECRET
        self._environment = environment or settings.PLAID_ENV
        self._base_url = _ENV_HOSTS.get(self._environment, _ENV_HOSTS["sandbox"])
        self._webhook_keys: dict[str, dict[str, Any]] = {}

    @property
    def environment(self) -> str:
        return self._environment

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not (self._client_id and self._secret):
            raise PlaidError(
                "missing_credentials",
                "PLAID_CLIENT_ID / PLAID_SECRET are not configured.",
            )
        payload = {"client_id": self._client_id, "secret": self._secret, **body}
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30.0) as client:
            response = await client.post(path, json=payload)
        try:
            data = response.json()
        except ValueError:
            # Non-JSON body (e.g. an HTML 502 from an upstream proxy). Surface it
            # as a PlaidError so callers get consistent error handling instead of
            # a raw JSONDecodeError.
            raise PlaidError(
                "invalid_response",
                f"Non-JSON response (HTTP {response.status_code}): "
                f"{response.text[:200]}",
            ) from None
        if response.status_code >= 400:
            raise PlaidError(
                data.get("error_code", "unknown_error"),
                data.get("error_message", response.text),
            )
        return data

    async def create_link_token(
        self,
        *,
        user_id: object,
        client_name: str = "Aegis Finance",
        products: list[str] | None = None,
    ) -> str:
        """Create a Link token the frontend hands to Plaid Link."""
        body: dict[str, Any] = {
            "user": {"client_user_id": str(user_id)},
            "client_name": client_name,
            "products": products or ["transactions"],
            "country_codes": ["US"],
            "language": "en",
        }
        webhook_url = get_webhook_url()
        if webhook_url:
            body["webhook"] = webhook_url
        if settings.PLAID_REDIRECT_URI:
            body["redirect_uri"] = settings.PLAID_REDIRECT_URI
        return (await self._post("/link/token/create", body))["link_token"]

    async def create_hosted_link(
        self,
        *,
        user_id: object,
        client_name: str = "Aegis Finance",
        products: list[str] | None = None,
        update_access_token: str | None = None,
    ) -> tuple[str, str]:
        """Create a Hosted Link session: Plaid hosts the entire connect UI.

        Returns ``(hosted_link_url, link_token)``. Open the URL in the browser;
        poll ``link_public_tokens(link_token)`` server-side for the result.
        ``update_access_token`` switches Link to update mode (re-auth of an
        existing Item): the token identifies the Item, products must be
        omitted, and the access token itself does not change.
        """
        body: dict[str, Any] = {
            "user": {"client_user_id": str(user_id)},
            "client_name": client_name,
            "country_codes": ["US"],
            "language": "en",
            "hosted_link": {},
        }
        if update_access_token is not None:
            body["access_token"] = update_access_token
        else:
            body["products"] = products or ["transactions"]
        webhook_url = get_webhook_url()
        if webhook_url:
            body["webhook"] = webhook_url
        data = await self._post("/link/token/create", body)
        return data["hosted_link_url"], data["link_token"]

    async def link_public_tokens(self, link_token: str) -> list[str]:
        """Public tokens produced by a (completed) Hosted Link session. Empty
        while the user hasn't finished — the caller polls until non-empty."""
        data = await self._post("/link/token/get", {"link_token": link_token})
        tokens: list[str] = []
        for session in data.get("link_sessions") or []:
            results = session.get("results") or {}
            for added in results.get("item_add_results") or []:
                public_token = added.get("public_token")
                if public_token:
                    tokens.append(public_token)
        return tokens

    async def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        """Exchange a public token for a long-lived (access_token, item_id)."""
        data = await self._post(
            "/item/public_token/exchange", {"public_token": public_token}
        )
        return data["access_token"], data["item_id"]

    async def get_accounts(
        self, access_token: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return ``(accounts, item)`` for a connection."""
        data = await self._post("/accounts/get", {"access_token": access_token})
        return data["accounts"], data.get("item", {})

    async def get_institution_name(self, institution_id: str) -> str | None:
        """Human-readable institution name for a Plaid institution id (``ins_*``).
        Returns None if Plaid can't resolve it."""
        data = await self._post(
            "/institutions/get_by_id",
            {"institution_id": institution_id, "country_codes": ["US"]},
        )
        return (data.get("institution") or {}).get("name")

    async def get_webhook_verification_key(self, key_id: str) -> dict[str, Any]:
        """The ES256 JWK Plaid signs webhooks with, fetched by ``kid``."""
        data = await self._post("/webhook_verification_key/get", {"key_id": key_id})
        return data["key"]

    async def verify_webhook(
        self, raw_body: bytes, verification_jwt: str
    ) -> dict[str, Any]:
        """Verify a webhook delivery's ``Plaid-Verification`` JWT.

        Checks — reject on any failure, never process an unverified body:
        ES256 only (no alg negotiation), signature against the ``kid``-fetched
        JWK (cached per client), body-hash claim against the RAW request bytes,
        and an ``iat`` freshness window. Returns the parsed JSON body.
        """
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import (
            encode_dss_signature,
        )

        try:
            header_b64, claims_b64, signature_b64 = verification_jwt.split(".")
            header = json.loads(_b64url_decode(header_b64))
            claims = json.loads(_b64url_decode(claims_b64))
            signature = _b64url_decode(signature_b64)
        except (ValueError, TypeError):
            raise _webhook_error("malformed verification JWT") from None

        if header.get("alg") != "ES256":
            raise _webhook_error(f"unexpected JWT alg {header.get('alg')!r}")
        key_id = header.get("kid")
        if not key_id:
            raise _webhook_error("verification JWT has no kid")

        jwk = self._webhook_keys.get(key_id)
        if jwk is None:
            jwk = await self.get_webhook_verification_key(key_id)
            self._webhook_keys[key_id] = jwk
        if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
            raise _webhook_error("verification key is not a P-256 EC key")

        public_key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(_b64url_decode(jwk["x"]), "big"),
            int.from_bytes(_b64url_decode(jwk["y"]), "big"),
            ec.SECP256R1(),
        ).public_key()
        if len(signature) != 64:
            raise _webhook_error("signature is not a raw ES256 r||s pair")
        der_signature = encode_dss_signature(
            int.from_bytes(signature[:32], "big"),
            int.from_bytes(signature[32:], "big"),
        )
        signing_input = f"{header_b64}.{claims_b64}".encode()
        try:
            public_key.verify(der_signature, signing_input, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            raise _webhook_error("signature verification failed") from None

        issued_at = claims.get("iat")
        if not isinstance(issued_at, int | float) or (
            time.time() - issued_at > _WEBHOOK_MAX_AGE_SECONDS
        ):
            raise _webhook_error("verification JWT is missing iat or too old")
        body_sha256 = hashlib.sha256(raw_body).hexdigest()
        if not hmac.compare_digest(
            body_sha256, str(claims.get("request_body_sha256", ""))
        ):
            raise _webhook_error("body hash does not match signed digest")

        try:
            return json.loads(raw_body)
        except ValueError:
            raise _webhook_error("webhook body is not valid JSON") from None

    async def get_liabilities(self, access_token: str) -> dict[str, Any]:
        """Liability detail keyed by lane (``credit`` / ``mortgage`` /
        ``student``). Callers capability-gate on the item's products first."""
        data = await self._post("/liabilities/get", {"access_token": access_token})
        return data.get("liabilities") or {}

    async def update_item_webhook(self, access_token: str, webhook_url: str) -> None:
        """Point an existing Item's webhook at a new URL (tunnel rotation)."""
        await self._post(
            "/item/webhook/update",
            {"access_token": access_token, "webhook": webhook_url},
        )

    async def remove_item(self, access_token: str) -> None:
        """Remove the Item at Plaid so the access token is invalidated and Plaid
        stops billing/updating it. Idempotent from our side: the caller disconnects
        locally regardless of the outcome here."""
        await self._post("/item/remove", {"access_token": access_token})

    async def sync_transactions(
        self, access_token: str, cursor: str | None = None
    ) -> dict[str, Any]:
        """One page of the cursor-based transaction sync (added/modified/removed
        + ``next_cursor`` + ``has_more``)."""
        body: dict[str, Any] = {"access_token": access_token}
        if cursor:
            body["cursor"] = cursor
        return await self._post("/transactions/sync", body)

    async def get_holdings(
        self, access_token: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return ``(holdings, securities)`` for an investments-enabled item."""
        data = await self._post(
            "/investments/holdings/get", {"access_token": access_token}
        )
        return data.get("holdings", []), data.get("securities", [])

    async def get_investment_transactions(
        self,
        access_token: str,
        start_date: str,
        end_date: str,
        *,
        offset: int = 0,
        count: int = 500,
    ) -> dict[str, Any]:
        """One page of ``/investments/transactions/get``.

        Unlike ``/transactions/sync`` this endpoint has no cursor: it pages a
        date range by ``offset`` and reports ``total_investment_transactions``.
        Callers re-fetch the window and dedup by ``investment_transaction_id``.
        Returns the raw payload (``investment_transactions`` + ``securities`` +
        ``total_investment_transactions``)."""
        return await self._post(
            "/investments/transactions/get",
            {
                "access_token": access_token,
                "start_date": start_date,
                "end_date": end_date,
                "options": {"offset": offset, "count": count},
            },
        )

    async def sandbox_public_token(
        self,
        *,
        institution_id: str = "ins_109508",
        products: list[str] | None = None,
    ) -> str:
        """Sandbox-only: mint a public token without the Link UI (for testing)."""
        data = await self._post(
            "/sandbox/public_token/create",
            {
                "institution_id": institution_id,
                "initial_products": products or ["transactions", "investments"],
            },
        )
        return data["public_token"]

    async def fire_sandbox_webhook(self, access_token: str, webhook_code: str) -> None:
        """Sandbox-only: make Plaid deliver a REAL (signed) webhook for the
        item, end-to-end testing PLAID_WEBHOOK_URL and verification."""
        await self._post(
            "/sandbox/item/fire_webhook",
            {"access_token": access_token, "webhook_code": webhook_code},
        )
