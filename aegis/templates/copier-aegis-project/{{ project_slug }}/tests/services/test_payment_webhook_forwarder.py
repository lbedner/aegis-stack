"""
Tests for the Overseer Stripe webhook auto-forwarder.

The hook launches ``stripe listen`` as a subprocess when the gate
passes and populates a runtime webhook secret for the payment provider.
These tests exercise each gate branch plus the secret-parse and
shutdown paths with the subprocess fully mocked — no real stripe-cli
invocation.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.components.backend.shutdown import (
    payment_webhook_forwarder as shutdown_mod,
)
from app.components.backend.startup import payment_webhook_forwarder as startup_mod
from app.services.payment.providers import stripe as stripe_provider_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_module_state() -> Generator[None]:
    """Clear the runtime secret and subprocess handle between tests."""
    stripe_provider_mod._RUNTIME_WEBHOOK_SECRET = None
    startup_mod.forwarder_process = None
    yield
    stripe_provider_mod._RUNTIME_WEBHOOK_SECRET = None
    startup_mod.forwarder_process = None


def _keys(
    secret_key: str = "sk_test_abc", webhook_secret: str = ""
) -> dict[str, str | None]:
    """The Stripe keys in effect, as ``secrets.get_many`` hands them over."""
    return {"STRIPE_SECRET_KEY": secret_key, "STRIPE_WEBHOOK_SECRET": webhook_secret}


@contextmanager
def _fake_settings(
    secret_key: str = "sk_test_abc",
    webhook_secret: str = "",
    port: int = 8000,
) -> Iterator[None]:
    """The port from settings, the keys from ``app.core.secrets``."""
    with (
        patch.object(startup_mod, "settings", SimpleNamespace(PORT=port)),
        patch.object(
            startup_mod.secrets,
            "get_many",
            AsyncMock(return_value=_keys(secret_key, webhook_secret)),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Gate branches
# ---------------------------------------------------------------------------


class TestForwarderGate:
    """``_should_auto_forward`` returns False with a reason on any skip."""

    def test_skips_when_not_test_mode(self) -> None:
        ok, reason = startup_mod._should_auto_forward(_keys(secret_key="sk_live_abc"))
        assert ok is False
        assert "not a test key" in reason

    def test_skips_when_webhook_secret_set(self) -> None:
        ok, reason = startup_mod._should_auto_forward(
            _keys(webhook_secret="whsec_user_set")
        )
        assert ok is False
        assert "set explicitly" in reason

    def test_skips_when_cli_missing(self) -> None:
        with (
            _fake_settings(),
            patch.object(startup_mod.shutil, "which", return_value=None),
        ):
            ok, reason = startup_mod._should_auto_forward(_keys())
        assert ok is False
        assert "Stripe CLI not installed" in reason

    def test_allows_when_all_gates_pass(self) -> None:
        with (
            _fake_settings(),
            patch.object(
                startup_mod.shutil, "which", return_value="/usr/local/bin/stripe"
            ),
        ):
            ok, reason = startup_mod._should_auto_forward(_keys())
        assert ok is True
        assert reason == ""


# ---------------------------------------------------------------------------
# Full startup with a mocked subprocess
# ---------------------------------------------------------------------------


class TestForwarderStartup:
    """End-to-end path: gate passes → Popen → secret line parsed → stored."""

    @pytest.mark.asyncio
    async def test_startup_skips_when_gate_fails(self) -> None:
        """Skip path must never touch subprocess or the runtime secret."""
        with (
            _fake_settings(secret_key="sk_live_abc"),
            patch.object(startup_mod.subprocess, "Popen") as popen,
        ):
            await startup_mod.startup_payment_webhook_forwarder()

        popen.assert_not_called()
        assert startup_mod.forwarder_process is None
        assert stripe_provider_mod._RUNTIME_WEBHOOK_SECRET is None

    @pytest.mark.asyncio
    async def test_startup_captures_secret_from_stdout(self) -> None:
        """Stripe-cli banner line yields a ``whsec_...`` → runtime secret."""
        banner = "Ready! Your webhook signing secret is whsec_abc123XYZ (^C to quit)\n"
        fake_stdout = MagicMock()
        # ``readline`` returns one line then signals EOF with ``""`` so the
        # background drain exits cleanly.
        fake_stdout.readline.side_effect = [banner, ""]
        fake_proc = MagicMock(stdout=fake_stdout)

        with (
            _fake_settings(),
            patch.object(
                startup_mod.shutil, "which", return_value="/usr/local/bin/stripe"
            ),
            patch.object(startup_mod.subprocess, "Popen", return_value=fake_proc),
        ):
            await startup_mod.startup_payment_webhook_forwarder()

        assert startup_mod.forwarder_process is fake_proc
        assert stripe_provider_mod._RUNTIME_WEBHOOK_SECRET == "whsec_abc123XYZ"

    @pytest.mark.asyncio
    async def test_startup_passes_api_key_to_stripe_listen(self) -> None:
        """``stripe listen`` is invoked with ``--api-key``.

        No ``stripe login`` is required.
        """
        banner = "Ready! Your webhook signing secret is whsec_xyz\n"
        fake_stdout = MagicMock()
        fake_stdout.readline.side_effect = [banner, ""]
        fake_proc = MagicMock(stdout=fake_stdout)

        with (
            _fake_settings(secret_key="sk_test_abc123"),
            patch.object(
                startup_mod.shutil, "which", return_value="/usr/local/bin/stripe"
            ),
            patch.object(
                startup_mod.subprocess, "Popen", return_value=fake_proc
            ) as popen,
        ):
            await startup_mod.startup_payment_webhook_forwarder()

        args = popen.call_args[0][0]
        assert args[:4] == ["stripe", "listen", "--api-key", "sk_test_abc123"]
        assert "--forward-to" in args


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


class TestForwarderShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_terminates_running_subprocess(self) -> None:
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # still running
        startup_mod.forwarder_process = fake_proc

        await shutdown_mod.shutdown_payment_webhook_forwarder()

        fake_proc.terminate.assert_called_once()
        fake_proc.wait.assert_called_once()
        assert startup_mod.forwarder_process is None

    @pytest.mark.asyncio
    async def test_shutdown_noop_when_no_subprocess(self) -> None:
        startup_mod.forwarder_process = None
        # Should not raise.
        await shutdown_mod.shutdown_payment_webhook_forwarder()

    @pytest.mark.asyncio
    async def test_shutdown_kills_if_terminate_times_out(self) -> None:
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.wait.side_effect = Exception("timeout")
        startup_mod.forwarder_process = fake_proc

        await shutdown_mod.shutdown_payment_webhook_forwarder()

        fake_proc.terminate.assert_called_once()
        fake_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# StripeProvider picks up the runtime override
# ---------------------------------------------------------------------------


class TestStripeProviderVerifyWebhook:
    """``verify_webhook`` must return a WebhookEvent with a plain-dict
    ``data`` field, not a ``stripe.StripeObject`` — the previous bug.

    Regression: ``stripe.StripeObject`` is dict-like but not a ``dict``
    instance. Pydantic v2 ``dict[str, Any]`` refuses to coerce it, and
    the workaround ``dict(obj)`` raises ``KeyError: 0`` on some event
    types (e.g. ``product.created``). Fix re-parses the verified raw
    JSON payload, giving us plain nested dicts.
    """

    def test_verify_webhook_returns_plain_dict_data(self) -> None:
        """Real-shape Stripe payload → WebhookEvent.data is a dict."""
        import json
        from unittest.mock import MagicMock, patch

        from app.services.payment.providers.stripe import StripeProvider

        payload_dict = {
            "id": "evt_test",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_test_123",
                    "amount_total": 2500,
                    "currency": "usd",
                    "mode": "payment",
                    "customer": None,
                }
            },
        }
        payload = json.dumps(payload_dict).encode()
        fake_event = MagicMock(type="checkout.session.completed")

        provider = StripeProvider()
        provider._webhook_secret = "whsec_test"

        with patch(
            "app.services.payment.providers.stripe.stripe.Webhook.construct_event",
            return_value=fake_event,
        ):
            import asyncio

            result = asyncio.run(provider.verify_webhook(payload, "sig"))

        assert result.event_type == "checkout.session.completed"
        assert isinstance(result.data, dict)
        assert result.data["id"] == "cs_test_123"
        assert result.data["amount_total"] == 2500


class TestStripeProviderRuntimeOverride:
    """``verify_webhook`` checks against the runtime secret first, then the
    one in effect from ``app.core.secrets``."""

    async def _secret_used(self) -> str:
        from app.services.payment.providers.stripe import StripeProvider

        seen: dict[str, str] = {}

        def construct(payload: bytes, signature: str, secret: str) -> SimpleNamespace:
            seen["secret"] = secret
            return SimpleNamespace(type="checkout.session.completed")

        with (
            patch.object(
                stripe_provider_mod.stripe.Webhook,
                "construct_event",
                side_effect=construct,
            ),
            patch.object(
                stripe_provider_mod.secrets,
                "get",
                AsyncMock(return_value="whsec_from_env"),
            ),
        ):
            await StripeProvider().verify_webhook(b"{}", "sig")
        return seen["secret"]

    async def test_provider_prefers_runtime_secret(self) -> None:
        from app.services.payment.providers.stripe import set_runtime_webhook_secret

        set_runtime_webhook_secret("whsec_from_runtime")
        assert await self._secret_used() == "whsec_from_runtime"

    async def test_provider_falls_back_to_the_secret_in_effect(self) -> None:
        assert stripe_provider_mod._RUNTIME_WEBHOOK_SECRET is None
        assert await self._secret_used() == "whsec_from_env"
