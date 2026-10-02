"""
Stripe webhook auto-forwarder startup hook.

When Overseer boots in Stripe test mode without an explicit
``STRIPE_WEBHOOK_SECRET``, this hook launches ``stripe listen`` as a
supervised subprocess and injects the signing secret it prints into the
payment provider at runtime. That way a fresh ``aegis init`` project
with only ``STRIPE_SECRET_KEY`` set receives test webhooks end-to-end
with zero extra configuration — same ``/webhook`` endpoint, same
``_handle_checkout_completed``, no new ingestion path.

Gates — we only auto-start the forwarder if ALL of:

1. ``STRIPE_SECRET_KEY`` starts with ``sk_test_`` (test mode).
2. ``STRIPE_WEBHOOK_SECRET`` is empty (user hasn't explicitly set one;
   if they did, they're using ngrok or a Stripe dashboard endpoint and
   we must not fight their setup).
3. The ``stripe`` CLI binary is on ``PATH``.

Missing any gate produces a single log line and a no-op — never an
exception. This is a convenience; it must degrade silently when the
environment can't support it (Docker without stripe-cli, CI, prod).

The paired shutdown hook in ``app/components/backend/shutdown/`` kills
the subprocess on exit.
"""

import asyncio
import re
import shutil
import subprocess
from typing import Any

from app.core import secrets
from app.core.config import settings
from app.core.log import logger
from app.services.payment.providers.stripe import set_runtime_webhook_secret

# Public for the shutdown hook. A ``Popen[str]`` on success, ``None``
# when the gate didn't pass.
forwarder_process: subprocess.Popen[str] | None = None

# Regex matching the signing secret line ``stripe listen`` prints after
# it connects. Format (Stripe CLI 1.x): ``Your webhook signing secret is
# whsec_abcdef... (^C to quit)``.
_WHSEC_RE = re.compile(r"(whsec_[A-Za-z0-9_]+)")

# How long to wait for the secret line before giving up. On a healthy
# `stripe listen` it arrives within ~1s; 5s is generous.
_SECRET_READ_TIMEOUT_SECONDS = 5.0


def _stripe_listen_args(port: int, api_key: str) -> list[str]:
    """Argv for ``stripe listen`` pointed at the local webhook endpoint.

    ``--api-key`` is passed explicitly so the subprocess authenticates
    via ``STRIPE_SECRET_KEY`` instead of the interactive ``stripe login``
    flow — that matters in Docker (no browser) and for fresh clones
    where nobody has logged stripe-cli into the user's Stripe account.
    """
    target = f"localhost:{port}/api/v1/payment/webhook"
    return ["stripe", "listen", "--api-key", api_key, "--forward-to", target]


STRIPE_KEYS = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")


def _should_auto_forward(keys: dict[str, str | None]) -> tuple[bool, str]:
    """Evaluate the gate on the Stripe keys in effect. Returns
    (should_start, reason_if_not)."""
    api_key = keys["STRIPE_SECRET_KEY"] or ""
    if not api_key.startswith("sk_test_"):
        return False, (
            "STRIPE_SECRET_KEY is not a test key; skipping auto-webhook-forwarder."
        )
    if keys["STRIPE_WEBHOOK_SECRET"]:
        return False, (
            "STRIPE_WEBHOOK_SECRET is set explicitly; skipping auto-webhook-forwarder."
        )
    if not shutil.which("stripe"):
        return False, (
            "Stripe CLI not installed; skipping auto-webhook-forwarder. "
            "Install stripe-cli or set STRIPE_WEBHOOK_SECRET manually to "
            "receive Stripe events in Overseer."
        )
    return True, ""


async def _drain_and_capture_secret(proc: subprocess.Popen[str]) -> None:
    """Read stdout until we see the signing-secret line, then stop.

    ``stripe listen`` keeps writing event lines for its whole lifetime;
    we only care about the initial "Ready! Your webhook signing secret
    is whsec_..." banner. After we capture it we leave the pipe open
    so the subprocess doesn't block on a full buffer, but stop tracking
    lines ourselves.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _SECRET_READ_TIMEOUT_SECONDS

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.warning(
                "Stripe webhook forwarder did not emit a signing secret "
                "within %.0fs; events may still fail verification.",
                _SECRET_READ_TIMEOUT_SECONDS,
            )
            # stripe-cli may still be spewing non-secret lines; keep draining
            # in the background so a full stdout pipe can't block the
            # subprocess and a late secret can still be captured.
            loop.create_task(_background_drain(proc))
            return

        # ``readline`` is blocking; push it onto the default executor so
        # the asyncio loop stays free. None guard handles the pipe
        # closing before we read anything.
        assert proc.stdout is not None
        try:
            line = await asyncio.wait_for(
                loop.run_in_executor(None, proc.stdout.readline),
                timeout=remaining,
            )
        except TimeoutError:
            # stripe-cli produced no output at all inside the window
            # (unauthenticated CLI, no network, ...). This hook is a dev
            # convenience — it must never take the app down. Keep draining
            # in the background so the pipe can't fill and so a late
            # secret still shows up in the logs.
            logger.warning(
                "Stripe webhook forwarder produced no output within %.0fs; "
                "continuing startup without a captured signing secret — "
                "webhook events may fail verification.",
                _SECRET_READ_TIMEOUT_SECONDS,
            )
            loop.create_task(_background_drain(proc))
            return
        if not line:
            logger.warning(
                "Stripe webhook forwarder stdout closed before emitting a "
                "signing secret; the subprocess may have exited."
            )
            return

        match = _WHSEC_RE.search(line)
        if match:
            secret = match.group(1)
            set_runtime_webhook_secret(secret)
            logger.info("Stripe webhook signing secret captured from stripe-cli")
            # Drain remaining stdout in the background so the subprocess
            # pipe doesn't fill up, but don't block startup further.
            loop.create_task(_background_drain(proc))
            return


async def _background_drain(proc: subprocess.Popen[str]) -> None:
    """Log stripe-cli stdout at info level and stop when it closes.

    Surfacing each line (event delivery lines like ``--> checkout.session.
    completed [evt_...]``) in Overseer's log stream turns the otherwise
    invisible forwarder into a debuggable participant: if events aren't
    landing in the DB, you can tell from the logs whether stripe-cli saw
    them at all.
    """
    loop = asyncio.get_running_loop()
    assert proc.stdout is not None
    while True:
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            logger.info("Stripe webhook forwarder stdout closed")
            return
        stripped = line.rstrip()
        if stripped:
            logger.info("stripe-cli: %s", stripped)
        match = _WHSEC_RE.search(line)
        if match:
            # Under boot load the ``stripe listen`` handshake can outlast
            # the startup capture window; catch a late-arriving secret
            # here instead of losing it (startup already continued with
            # a warning in that case).
            set_runtime_webhook_secret(match.group(1))
            logger.info(
                "Stripe webhook signing secret captured from stripe-cli "
                "(late, after the startup window)"
            )


async def startup_payment_webhook_forwarder() -> None:
    """Launch ``stripe listen`` subprocess if the gate permits."""
    global forwarder_process

    keys = await secrets.get_many(*STRIPE_KEYS)
    should_start, reason = _should_auto_forward(keys)
    if not should_start:
        logger.info(reason)
        return

    # ``_should_auto_forward`` confirmed a non-empty ``sk_test_...`` key;
    # the ``or ""`` narrows the type for callers that treat ``str | None``
    # strictly.
    args = _stripe_listen_args(settings.PORT, keys["STRIPE_SECRET_KEY"] or "")
    try:
        forwarder_process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered — secret arrives as a single line
        )
    except OSError as e:
        logger.warning("Stripe webhook forwarder failed to launch: %s", e)
        forwarder_process = None
        return

    logger.info(
        "Stripe webhook forwarder started: stripe listen → /api/v1/payment/webhook"
    )

    await _drain_and_capture_secret(forwarder_process)


# Export hook(s) for auto-discovery by ``app/components/backend/hooks.py``.
startup_hook: Any = startup_payment_webhook_forwarder
