"""SnapTrade API client — a thin async wrapper over the official SDK exposing
only the calls the finance service uses (the SDK signs every request with the
partner HMAC automatically).

SnapTrade's model differs from Plaid's in three ways that shape this surface:

- Per end-user auth: one registered SnapTrade user (``user_id`` +
  ``user_secret``) per app user; every data call passes the pair. There is no
  per-connection access token — a brokerage login becomes an "authorization"
  under the user.
- Connect is a redirect portal: ``login_url`` returns a short-lived (5 min)
  URL where the user completes the brokerage OAuth; afterwards the new
  authorization simply shows up in ``list_authorizations`` — nothing to
  exchange.
- No cursor deltas or webhook nudges: sync is polling (accounts, positions,
  date-windowed + offset-paged activities), with SnapTrade refreshing its own
  upstream cache roughly daily.

Sign convention (verified against SnapTrade's docs): activity ``amount`` is
positive for cash INTO the account (sell/dividend/deposit) and negative for
cash out (buy/withdrawal/fee) — already this project's convention, so unlike
Plaid there is NO negation on ingest.

The SDK import is deferred into ``_sdk()`` on purpose: this module is always
generated, but ``snaptrade-python-sdk`` is only a dependency when the
``finance_snaptrade`` flag is on, and ``connections`` imports this
module unconditionally.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import settings


class SnapTradeError(RuntimeError):
    """A SnapTrade API error (``error_code`` carries the machine-readable
    reason — the HTTP status when nothing better is available)."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(f"{error_code}: {message}")


def _body(response: Any) -> Any:
    """Unwrap an SDK response to its payload (plain dict/list)."""
    return getattr(response, "body", response)


class SnapTradeClient:
    """Async SnapTrade client. Reads partner credentials from settings unless
    overridden (handy for tests)."""

    def __init__(
        self, *, client_id: str | None = None, consumer_key: str | None = None
    ) -> None:
        self._client_id = client_id or getattr(settings, "SNAPTRADE_CLIENT_ID", None)
        self._consumer_key = consumer_key or getattr(
            settings, "SNAPTRADE_CONSUMER_KEY", None
        )
        self._client: Any = None

    @property
    def is_personal(self) -> bool:
        """Personal (``PERS-``) keys are the account owner's own credentials:
        there is no per-user registration (``registerUser`` returns 400), and
        data calls are signed with an EMPTY ``userId``/``userSecret`` pair (the
        API resolves the owner from the key; SnapTrade's docs say to omit the
        pair, and the SDK accepts empty strings)."""
        return bool(self._client_id and self._client_id.startswith("PERS-"))

    def _sdk(self) -> Any:
        if not (self._client_id and self._consumer_key):
            raise SnapTradeError(
                "missing_credentials",
                "SNAPTRADE_CLIENT_ID / SNAPTRADE_CONSUMER_KEY are not configured.",
            )
        if self._client is None:
            from snaptrade_client import SnapTrade, SnapTradeAuth

            # The auth MODE matters: the plain-kwargs constructor configures
            # no request signing for PERS- keys and every call comes back
            # 401 "credentials were not provided". Personal keys need the
            # SDK's ``personalApiKey`` mode; partner keys the commercial one.
            build_auth = (
                SnapTradeAuth.personal_api_key
                if self.is_personal
                else SnapTradeAuth.commercial_api_key
            )
            self._client = SnapTrade(
                auth=build_auth(
                    consumer_key=self._consumer_key, client_id=self._client_id
                )
            )
        return self._client

    async def _call(self, method: Any, /, **kwargs: Any) -> Any:
        from snaptrade_client.exceptions import ApiException

        try:
            # SYNC SDK methods in a worker thread, not the ``a``-prefixed
            # async variants: this SDK release's async response handling
            # calls ``supports_chunked_reads()`` on an aiohttp response,
            # which has no such method, and crashes after a successful call.
            return _body(await asyncio.to_thread(lambda: method(**kwargs)))
        except ApiException as exc:
            # Prefer SnapTrade's numeric body code (e.g. 1010 "user already
            # exists") over the bare HTTP status: callers gate recovery
            # behavior on it.
            body = getattr(exc, "body", None)
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except ValueError:
                    body = None
            code = body.get("code") if isinstance(body, dict) else None
            raise SnapTradeError(
                str(code or getattr(exc, "status", "") or "api_error"), str(exc)
            ) from exc

    # -- User lifecycle ------------------------------------------------------

    async def register_user(self, user_id: str) -> str:
        """Register a SnapTrade user; returns the ``user_secret`` (the caller
        encrypts and stores it — it IS the access credential)."""
        if self.is_personal:
            raise SnapTradeError(
                "personal_key", "registerUser is not available for personal keys."
            )
        body = await self._call(
            self._sdk().authentication.register_snap_trade_user, user_id=user_id
        )
        secret = body.get("userSecret") or body.get("user_secret")
        if not secret:
            raise SnapTradeError("invalid_response", "registerUser returned no secret")
        return str(secret)

    async def delete_user(self, user_id: str) -> None:
        """Delete a SnapTrade user (removes all its authorizations). Used to
        recover when a user exists but its secret was lost."""
        await self._call(
            self._sdk().authentication.delete_snap_trade_user, user_id=user_id
        )

    async def login_url(
        self,
        user_id: str,
        user_secret: str,
        *,
        broker: str | None = None,
        custom_redirect: str | None = None,
    ) -> str:
        """A connection-portal URL (expires in ~5 minutes) where the user
        completes the brokerage OAuth."""
        kwargs: dict[str, Any] = {"user_id": user_id, "user_secret": user_secret}
        if broker:
            kwargs["broker"] = broker
        if custom_redirect:
            kwargs["custom_redirect"] = custom_redirect
        body = await self._call(
            self._sdk().authentication.login_snap_trade_user, **kwargs
        )
        url = body.get("redirectURI") or body.get("redirect_uri")
        if not url:
            raise SnapTradeError("invalid_response", "login returned no redirect URI")
        return str(url)

    # -- Connections (brokerage authorizations) -------------------------------

    async def list_authorizations(
        self, user_id: str, user_secret: str
    ) -> list[dict[str, Any]]:
        """Every brokerage authorization (completed connection) for the user."""
        body = await self._call(
            self._sdk().connections.list_brokerage_authorizations,
            user_id=user_id,
            user_secret=user_secret,
        )
        return list(body or [])

    async def remove_authorization(
        self, user_id: str, user_secret: str, authorization_id: str
    ) -> None:
        """Revoke one brokerage authorization at SnapTrade."""
        await self._call(
            self._sdk().connections.remove_brokerage_authorization,
            user_id=user_id,
            user_secret=user_secret,
            authorization_id=authorization_id,
        )

    # -- Data fetch ------------------------------------------------------------

    async def list_accounts(
        self, user_id: str, user_secret: str
    ) -> list[dict[str, Any]]:
        """All brokerage accounts across the user's authorizations (each row
        carries ``brokerage_authorization`` to scope it to a connection)."""
        body = await self._call(
            self._sdk().account_information.list_user_accounts,
            user_id=user_id,
            user_secret=user_secret,
        )
        return list(body or [])

    async def get_positions(
        self, user_id: str, user_secret: str, account_id: str
    ) -> list[dict[str, Any]]:
        """Current positions for one account.

        ``/positions/all`` returns every instrument kind (stock, ETF, option,
        crypto, future, ...) in one ``results`` list, each row discriminated
        by ``instrument.kind``."""
        body = await self._call(
            self._sdk().account_information.get_all_account_positions,
            user_id=user_id,
            user_secret=user_secret,
            account_id=account_id,
        )
        if isinstance(body, dict):
            return list(body.get("results") or [])
        return list(body or [])

    async def get_activities(
        self,
        user_id: str,
        user_secret: str,
        account_id: str,
        *,
        start_date: str,
        end_date: str,
        offset: int = 0,
        limit: int = 500,
    ) -> dict[str, Any]:
        """One page of account activities (trades, dividends, cash movements)
        in a date window. Returns ``{"data": [...], "pagination": {...}}``."""
        body = await self._call(
            self._sdk().account_information.get_account_activities,
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
            start_date=start_date,
            end_date=end_date,
            offset=offset,
            limit=limit,
        )
        if isinstance(body, dict):
            return body
        # Defensive: some SDK versions return the bare list.
        return {"data": list(body or []), "pagination": {}}
