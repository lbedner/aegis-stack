"""
Communications service CLI commands.

Command-line interface for email, SMS, and voice call functionality.
"""

import asyncio

import typer
from app.cli import theme
from app.i18n import lazy_t, t
from rich.table import Table

# Default TwiML URL for testing voice calls
TWILIO_DEMO_TWIML_URL = "http://demo.twilio.com/docs/voice.xml"

app = typer.Typer(help=lazy_t("comms.help"))
console = theme.console()

# Known service-layer warnings mapped to i18n keys
_WARNING_KEYS: dict[str, str] = {
    "RESEND_API_KEY": "comms.warn.resend_api_key",
    "RESEND_FROM_EMAIL": "comms.warn.resend_from_email",
    "TWILIO_ACCOUNT_SID": "comms.warn.twilio_account_sid",
    "TWILIO_AUTH_TOKEN": "comms.warn.twilio_auth_token",
    "TWILIO_MESSAGING_SERVICE_SID": "comms.warn.twilio_messaging_sid",
    "TWILIO_PHONE_NUMBER": "comms.warn.twilio_phone",
}

# ConfigurationError messages from send/call functions
_CONFIG_ERROR_KEYS: dict[str, str] = {
    "Twilio credentials not set": "comms.warn.twilio_creds",
    "RESEND_API_KEY is not set. Sign up": "comms.warn.resend_api_key_send",
}


def _translate_warning(warning: str) -> str:
    """Translate known service-layer warnings and errors at display time."""
    for env_var, key in _WARNING_KEYS.items():
        if env_var in warning:
            return t(key)
    for prefix, key in _CONFIG_ERROR_KEYS.items():
        if warning.startswith(prefix):
            return t(key)
    return warning


# Email command group
email_app = typer.Typer(help=lazy_t("comms.help_email"))
app.add_typer(email_app, name="email")

# SMS command group
sms_app = typer.Typer(help=lazy_t("comms.help_sms"))
app.add_typer(sms_app, name="sms")

# Call command group
call_app = typer.Typer(help=lazy_t("comms.help_call"))
app.add_typer(call_app, name="call")


@app.command(help=lazy_t("comms.help_status"))
def status() -> None:
    from app.services.comms.calls import get_call_status, validate_call_config
    from app.services.comms.email import get_email_status, validate_email_config
    from app.services.comms.sms import get_sms_status, validate_sms_config

    theme.title(t("comms.service_status_title"))

    # Email status
    email_status = get_email_status()
    email_errors = validate_email_config()

    theme.title(f"\n{t('comms.email_resend_header')}")
    status_label = t("comms.status_label")
    status_text = (
        t("comms.configured")
        if email_status["configured"]
        else t("comms.not_configured")
    )
    status_styled = (
        theme.good_text(status_text)
        if email_status["configured"]
        else theme.bad_text(status_text)
    )
    typer.echo(f"  {status_label} {status_styled}")
    api_key_label = t("comms.api_key_label")
    api_key_text = t("comms.set") if email_status["api_key_set"] else t("comms.not_set")
    api_key_styled = (
        theme.good_text(api_key_text)
        if email_status["api_key_set"]
        else theme.bad_text(api_key_text)
    )
    typer.echo(f"  {api_key_label} {api_key_styled}")
    from_label = t("comms.from_email_label")
    from_value = email_status["from_email"] or theme.bad_text(t("comms.not_set"))
    typer.echo(f"  {from_label} {from_value}")

    if email_errors:
        for error in email_errors:
            theme.warn(
                f"  {t('comms.warning', message=_translate_warning(error))}",
            )

    # SMS status
    sms_status = get_sms_status()
    sms_errors = validate_sms_config()

    theme.title(f"\n{t('comms.sms_twilio_header')}")
    status_label = t("comms.status_label")
    status_text = (
        t("comms.configured") if sms_status["configured"] else t("comms.not_configured")
    )
    status_styled = (
        theme.good_text(status_text)
        if sms_status["configured"]
        else theme.bad_text(status_text)
    )
    typer.echo(f"  {status_label} {status_styled}")
    sid_label = t("comms.account_sid_label")
    sid_text = t("comms.set") if sms_status["account_sid_set"] else t("comms.not_set")
    sid_styled = (
        theme.good_text(sid_text)
        if sms_status["account_sid_set"]
        else theme.bad_text(sid_text)
    )
    typer.echo(f"  {sid_label} {sid_styled}")
    auth_label = t("comms.auth_token_label")
    auth_text = t("comms.set") if sms_status["auth_token_set"] else t("comms.not_set")
    auth_styled = (
        theme.good_text(auth_text)
        if sms_status["auth_token_set"]
        else theme.bad_text(auth_text)
    )
    typer.echo(f"  {auth_label} {auth_styled}")
    msg_label = t("comms.messaging_service_label")
    msg_set = sms_status.get("messaging_service_sid_set")
    msg_text = t("comms.set") if msg_set else t("comms.not_set")
    msg_styled = theme.good_text(msg_text) if msg_set else theme.bad_text(msg_text)
    typer.echo(f"  {msg_label} {msg_styled}")
    phone_label = t("comms.phone_number_label")
    phone_value = sms_status["phone_number"] or theme.bad_text(t("comms.not_set"))
    typer.echo(f"  {phone_label} {phone_value}")

    if sms_errors:
        for error in sms_errors:
            theme.warn(
                f"  {t('comms.warning', message=_translate_warning(error))}",
            )

    # Voice status
    call_status = get_call_status()
    call_errors = validate_call_config()

    theme.title(f"\n{t('comms.voice_twilio_header')}")
    status_label = t("comms.status_label")
    status_text = (
        t("comms.configured")
        if call_status["configured"]
        else t("comms.not_configured")
    )
    status_styled = (
        theme.good_text(status_text)
        if call_status["configured"]
        else theme.bad_text(status_text)
    )
    typer.echo(f"  {status_label} {status_styled}")
    sid_label = t("comms.account_sid_label")
    sid_text = t("comms.set") if call_status["account_sid_set"] else t("comms.not_set")
    sid_styled = (
        theme.good_text(sid_text)
        if call_status["account_sid_set"]
        else theme.bad_text(sid_text)
    )
    typer.echo(f"  {sid_label} {sid_styled}")
    auth_label = t("comms.auth_token_label")
    auth_text = t("comms.set") if call_status["auth_token_set"] else t("comms.not_set")
    auth_styled = (
        theme.good_text(auth_text)
        if call_status["auth_token_set"]
        else theme.bad_text(auth_text)
    )
    typer.echo(f"  {auth_label} {auth_styled}")
    phone_label = t("comms.phone_number_label")
    phone_value = call_status["phone_number"] or theme.bad_text(t("comms.not_set"))
    typer.echo(f"  {phone_label} {phone_value}")

    if call_errors:
        for error in call_errors:
            theme.warn(
                f"  {t('comms.warning', message=_translate_warning(error))}",
            )

    # Summary
    typer.echo()
    services_configured = sum(
        [
            email_status["configured"],
            sms_status["configured"],
            call_status["configured"],
        ]
    )
    summary_text = t("comms.services_configured_summary", count=services_configured)
    if services_configured == 3:
        theme.good(summary_text, bold=True)
    else:
        theme.warn(summary_text, bold=True)

    if services_configured < 3:
        theme.label(f"\n{t('comms.quick_start')}")
        if not email_status["configured"]:
            theme.label(f"  {t('comms.email_signup_hint')}")
        if not sms_status["configured"] or not call_status["configured"]:
            theme.label(f"  {t('comms.twilio_signup_hint')}")


@email_app.command("send", help=lazy_t("comms.help_email_send"))
def email_send(
    to: str = typer.Argument(..., help=lazy_t("comms.arg_to_email")),
    subject: str = typer.Option(
        ..., "--subject", "-s", help=lazy_t("comms.opt_subject")
    ),
    text: str | None = typer.Option(
        None, "--text", "-t", help=lazy_t("comms.opt_text")
    ),
    html: str | None = typer.Option(None, "--html", help=lazy_t("comms.opt_html")),
) -> None:
    asyncio.run(_email_send(to, subject, text, html))


async def _email_send(
    to: str,
    subject: str,
    text: str | None,
    html: str | None,
) -> None:
    """Async implementation of email send."""
    from app.services.comms.email import (
        EmailConfigurationError,
        EmailError,
        send_email_simple,
    )

    if not text and not html:
        theme.bad(t("comms.text_or_html_required"))
        raise typer.Exit(1)

    try:
        result = await send_email_simple(
            to=to,
            subject=subject,
            text=text,
            html=html,
        )

        theme.good(t("comms.email_sent"), bold=True)
        msg_id_label = theme.label_text(t("comms.message_id_label"))
        typer.echo(f"{msg_id_label} {result.id}")
        to_label = theme.label_text(t("comms.to_label"))
        typer.echo(f"{to_label} {', '.join(result.to)}")
        subject_label = theme.label_text(t("comms.subject_label"))
        typer.echo(f"{subject_label} {subject}")

    except EmailConfigurationError as e:
        theme.bad(
            t("comms.configuration_error", error=_translate_warning(str(e))),
        )
        raise typer.Exit(1)
    except EmailError as e:
        theme.bad(t("comms.email_send_failed", error=e))
        raise typer.Exit(1)


@sms_app.command("send", help=lazy_t("comms.help_sms_send"))
def sms_send(
    to: str = typer.Argument(..., help=lazy_t("comms.arg_to_phone")),
    body: str = typer.Argument(..., help=lazy_t("comms.arg_body")),
) -> None:
    asyncio.run(_sms_send(to, body))


async def _sms_send(to: str, body: str) -> None:
    """Async implementation of SMS send."""
    from app.services.comms.sms import SMSConfigurationError, SMSError, send_sms_simple

    try:
        result = await send_sms_simple(to=to, body=body)

        theme.good(t("comms.sms_sent"), bold=True)
        sid_label = theme.label_text(t("comms.message_sid_label"))
        typer.echo(f"{sid_label} {result.sid}")
        to_label = theme.label_text(t("comms.to_label"))
        typer.echo(f"{to_label} {result.to}")
        seg_label = theme.label_text(t("comms.segments_label"))
        typer.echo(f"{seg_label} {result.segments}")

    except SMSConfigurationError as e:
        theme.bad(
            t("comms.configuration_error", error=_translate_warning(str(e))),
        )
        raise typer.Exit(1)
    except SMSError as e:
        theme.bad(t("comms.sms_send_failed", error=e))
        raise typer.Exit(1)


@call_app.command("make", help=lazy_t("comms.help_call_make"))
def call_make(
    to: str = typer.Argument(..., help=lazy_t("comms.arg_to_phone")),
    twiml_url: str = typer.Argument(
        TWILIO_DEMO_TWIML_URL, help=lazy_t("comms.arg_twiml_url")
    ),
    timeout: int = typer.Option(
        30, "--timeout", "-t", help=lazy_t("comms.opt_timeout")
    ),
) -> None:
    asyncio.run(_call_make(to, twiml_url, timeout))


async def _call_make(to: str, twiml_url: str, timeout: int) -> None:
    """Async implementation of make call."""
    from app.services.comms.calls import CallConfigurationError, CallError, make_call
    from app.services.comms.models import MakeCallRequest

    try:
        request = MakeCallRequest(to=to, twiml_url=twiml_url, timeout=timeout)
        result = await make_call(request)

        theme.good(t("comms.call_initiated"), bold=True)
        sid_label = theme.label_text(t("comms.call_sid_label"))
        typer.echo(f"{sid_label} {result.sid}")
        to_label = theme.label_text(t("comms.to_label"))
        typer.echo(f"{to_label} {result.to}")
        status_label = theme.label_text(t("comms.call_status_label"))
        typer.echo(f"{status_label} {result.status}")

    except CallConfigurationError as e:
        theme.bad(
            t("comms.configuration_error", error=_translate_warning(str(e))),
        )
        raise typer.Exit(1)
    except CallError as e:
        theme.bad(t("comms.call_failed", error=e))
        raise typer.Exit(1)


@app.command("providers", help=lazy_t("comms.help_providers"))
def providers() -> None:
    table = Table(title=t("comms.providers_title"), width=70)
    table.add_column(t("comms.channel_column"), style=theme.ACCENT, width=10)
    table.add_column(t("comms.provider_column"), width=10)
    table.add_column(t("comms.free_tier_column"), style="dim", width=12)
    table.add_column(t("comms.notes_column"), style="dim", width=30)

    table.add_row(
        t("comms.email"),
        "Resend",
        t("comms.free_tier_100_day"),
        t("comms.resend_notes"),
    )
    table.add_row(
        t("comms.sms"),
        "Twilio",
        t("comms.free_tier_15_trial"),
        t("comms.twilio_sms_notes"),
    )
    table.add_row(
        t("comms.voice"),
        "Twilio",
        t("comms.free_tier_15_trial"),
        t("comms.twilio_voice_notes"),
    )

    console.print(table)

    theme.label(f"\n{t('comms.signup_links')}")
    theme.label("  Resend: https://resend.com")
    theme.label("  Twilio: https://twilio.com/try-twilio")


if __name__ == "__main__":
    app()
