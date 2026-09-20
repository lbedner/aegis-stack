"""What each read-only payment command prints."""

from typing import TYPE_CHECKING

from rich.table import Table
import typer

from app.cli import theme
from app.i18n import t

if TYPE_CHECKING:
    pass

console = theme.console()


async def _status() -> None:
    """Async implementation of status command."""
    from app.core.db import get_async_session
    from app.services.payment.service import PaymentService

    async with get_async_session() as session:
        service = PaymentService(session)
        summary = await service.get_status_summary()

    mode = (
        f"[{theme.WARNING}]{t('payment.mode_test')}[/]"
        if summary.is_test_mode
        else f"[{theme.ACCENT}]{t('payment.mode_live')}[/]"
    )
    health = (
        f"[{theme.ACCENT}]{t('payment.connected')}[/]"
        if summary.healthy
        else f"[{theme.ERROR}]{t('payment.disconnected')}[/]"
    )

    console.print()
    console.print(f"[bold]{t('payment.status_title')}[/bold]")
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim")
    table.add_column("Value")

    table.add_row(t("payment.col_provider"), summary.provider_display_name)
    table.add_row(t("payment.col_mode"), mode)
    table.add_row(t("payment.col_status"), health)
    if summary.api_version:
        table.add_row(t("payment.col_api_version"), summary.api_version)
    table.add_row(t("payment.col_transactions"), str(summary.total_transactions))
    table.add_row(
        t("payment.col_revenue"),
        f"${summary.total_revenue_cents / 100:,.2f}",
    )
    table.add_row(t("payment.col_active_subs"), str(summary.active_subscriptions))
    if summary.open_disputes:
        table.add_row(
            t("payment.col_open_disputes"),
            f"[{theme.ERROR}]{summary.open_disputes}[/]",
        )

    console.print(table)
    console.print()

    if not summary.healthy and summary.health_message:
        console.print(
            f"[{theme.WARNING}]{t('payment.warning')}[/] {summary.health_message}"
        )
        console.print()


async def _transactions(limit: int, status_filter: str | None) -> None:
    """Async implementation of transactions command."""
    from app.core.db import get_async_session
    from app.services.payment.service import PaymentService

    async with get_async_session() as session:
        service = PaymentService(session)
        txns, total = await service.get_transactions(
            page=1, page_size=limit, status=status_filter
        )

    if not txns:
        console.print(f"[dim]{t('payment.no_transactions')}[/dim]")
        return

    table = Table(title=t("payment.transactions_title", total=total))
    table.add_column(t("payment.col_id"), style="dim")
    table.add_column(t("payment.col_type"))
    table.add_column(t("payment.col_status"))
    table.add_column(t("payment.col_amount"), justify="right")
    table.add_column(t("payment.col_currency"))
    table.add_column(t("payment.col_date"))

    status_colors = {
        "succeeded": theme.ACCENT,
        "pending": theme.WARNING,
        "failed": theme.ERROR,
        "refunded": "dim",
        "partially_refunded": "dim",
    }

    for txn in txns:
        color = status_colors.get(txn.status)
        status_cell = f"[{color}]{txn.status}[/]" if color else txn.status
        table.add_row(
            str(txn.id),
            txn.type,
            status_cell,
            f"${txn.amount / 100:,.2f}",
            txn.currency.upper(),
            txn.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


async def _disputes(status_filter: str | None) -> None:
    """Async implementation of disputes command."""
    from app.core.db import get_async_session
    from app.services.payment.service import PaymentService

    async with get_async_session() as session:
        service = PaymentService(session)
        rows = await service.get_disputes(status=status_filter)

    if not rows:
        console.print(f"[dim]{t('payment.no_disputes')}[/dim]")
        return

    title = t("payment.disputes_title")
    if status_filter:
        title = t("payment.disputes_title_filtered", status=status_filter)

    table = Table(title=t("payment.disputes_count", title=title, count=len(rows)))
    table.add_column(t("payment.col_id"), style="dim")
    table.add_column(t("payment.col_txn"), style="dim")
    table.add_column(t("payment.col_provider_id"), style="dim")
    table.add_column(t("payment.col_status"))
    table.add_column(t("payment.col_reason"))
    table.add_column(t("payment.col_amount"), justify="right")
    table.add_column(t("payment.col_due"))
    table.add_column(t("payment.col_created"))

    status_colors = {
        "warning_issued": theme.WARNING,
        "warning_closed": theme.ACCENT,
        "needs_response": theme.ERROR,
        "under_review": "dim",
        "won": theme.ACCENT,
        "lost": theme.ERROR,
        "charge_refunded": "dim",
    }

    for d in rows:
        color = status_colors.get(d.status)
        status_cell = f"[{color}]{d.status}[/]" if color else d.status
        due_cell = d.evidence_due_by.strftime("%Y-%m-%d") if d.evidence_due_by else "-"
        table.add_row(
            str(d.id),
            str(d.transaction_id),
            d.provider_dispute_id,
            status_cell,
            d.reason or "-",
            f"${d.amount / 100:,.2f}",
            due_cell,
            d.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


async def _seed(reset: bool, clear: bool) -> None:
    """Async implementation of seed command."""
    from app.core.db import get_async_session, init_database
    from app.services.payment.demo_seed import clear_fake_data, seed_fake_data
    from app.services.payment.service import PaymentService

    # Ensure tables exist when running the CLI against a fresh DB.
    init_database()

    async with get_async_session() as session:
        if reset or clear:
            await clear_fake_data(session)
            console.print(f"[{theme.WARNING}]{t('payment.wiped_rows')}[/]")

        if clear:
            return

        service = PaymentService(session)
        provider = await service.get_or_create_provider()
        try:
            summary = await seed_fake_data(session, provider)
        except RuntimeError as e:
            console.print(f"[{theme.WARNING}]{t('payment.nothing_to_do')}[/] {e}")
            raise typer.Exit(0) from e

    console.print()
    console.print(f"[bold {theme.ACCENT}]{t('payment.seed_success')}[/]")
    console.print()
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(t("payment.col_kind"), style="dim")
    table.add_column(t("payment.col_count"), justify="right")
    for key, val in summary.items():
        table.add_row(key.capitalize(), str(val))
    console.print(table)
    console.print()
    console.print(f"[dim]{t('payment.seed_view_via_dashboard')}[/dim]")
    console.print(f"  [{theme.ACCENT}]my-app payment transactions[/]")
    console.print(f"  [{theme.ACCENT}]my-app payment disputes[/]")
