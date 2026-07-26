"""
Payment Service Detail Modal

Tabbed interface for interacting with the payment service:
- Overview: Provider status, key metrics, open-dispute badge
- Transactions: Recent transactions with status coloring
- Subscriptions: Active subscriptions and billing periods
- Disputes: Chargebacks and early fraud warnings with evidence deadlines
"""

from datetime import datetime
from typing import Any

import flet as ft
from app.components.frontend import styles
from app.components.frontend.controls import (
    BodyText,
    DataTable,
    DataTableColumn,
    H3Text,
    LabelText,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.buttons import (
    BaseIconButton,
    PulseButton,
)
from app.components.frontend.controls.form_fields import FormDropdown, FormTextField
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings
from app.services.payment.constants import RefundReason
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import EmptyStatePlaceholder, MetricCard, StatRowsSection

# Transaction statuses that are refundable via POST /api/v1/payment/refund/{id}.
_REFUNDABLE_STATUSES = {"succeeded", "partially_refunded"}
_REFUNDABLE_TYPES = {"charge", "subscription"}

# ---------------------------------------------------------------------------
# Status -> Theme color mapping
# ---------------------------------------------------------------------------

_TRANSACTION_STATUS_COLORS: dict[str, str] = {
    "succeeded": Theme.Colors.SUCCESS,
    "pending": Theme.Colors.WARNING,
    "failed": Theme.Colors.ERROR,
    "refunded": Theme.Colors.INFO,
    "partially_refunded": Theme.Colors.INFO,
    "canceled": Theme.Colors.ERROR,
}

_SUBSCRIPTION_STATUS_COLORS: dict[str, str] = {
    "active": Theme.Colors.SUCCESS,
    "trialing": Theme.Colors.INFO,
    "past_due": Theme.Colors.WARNING,
    "canceled": Theme.Colors.ERROR,
    "unpaid": Theme.Colors.ERROR,
    "incomplete": Theme.Colors.WARNING,
}

_DISPUTE_STATUS_COLORS: dict[str, str] = {
    "warning_issued": Theme.Colors.WARNING,
    "warning_closed": Theme.Colors.SUCCESS,
    "needs_response": Theme.Colors.ERROR,
    "under_review": Theme.Colors.INFO,
    "won": Theme.Colors.SUCCESS,
    "lost": Theme.Colors.ERROR,
    "charge_refunded": Theme.Colors.INFO,
}


def _fmt_amount(amount_cents: int, currency: str = "usd") -> str:
    """Render a cents amount as a currency string."""
    symbol = "$" if currency.lower() == "usd" else ""
    suffix = "" if symbol else currency.upper()
    return f"{symbol}{amount_cents / 100:,.2f} {suffix}".strip()


def _fmt_datetime(iso_str: str | None) -> str:
    """Render an ISO datetime string as a compact display string."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_str


def _fmt_date(iso_str: str | None) -> str:
    """Render an ISO datetime string as a date-only display string."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return iso_str


# =============================================================================
# Overview Tab
# =============================================================================


class OverviewTab(ft.Container):
    """Key metrics + a 30-day revenue trend chart."""

    # How many days of revenue to plot. 30 is short enough that daily
    # granularity still reads well and long enough to show a trend.
    _REVENUE_WINDOW_DAYS = 30

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}

        total_txns = metadata.get("total_transactions", 0)
        revenue_cents = metadata.get("total_revenue_cents", 0)
        active_subs = metadata.get("active_subscriptions", 0)
        open_disputes = metadata.get("open_disputes", 0)

        # Metric cards row — mirrors database_modal's layout
        metric_cards = ft.Row(
            [
                MetricCard(
                    "Transactions",
                    f"{total_txns:,}",
                    Theme.Colors.INFO,
                ),
                MetricCard(
                    "Revenue",
                    f"${revenue_cents / 100:,.2f}",
                    Theme.Colors.SUCCESS,
                ),
                MetricCard(
                    "Subscriptions",
                    str(active_subs),
                    Theme.Colors.INFO,
                ),
                MetricCard(
                    "Open Disputes",
                    str(open_disputes),
                    Theme.Colors.ERROR if open_disputes else Theme.Colors.SUCCESS,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
        )

        # Chart placeholder — async-populated by _load_revenue on mount.
        # Rendered inside a bordered card so it matches the modal's rhythm
        # before data arrives. Height tuned so the axis labels and curve
        # have breathing room; LineChart's label_size (40px left, 20px
        # bottom) alone eats ~60px, so a 240px box left <180px of plot
        # area and the curve visibly clipped.
        self._chart_container = ft.Container(
            content=ft.Row(
                [BodyText("Loading revenue…")],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            padding=ft.padding.all(Theme.Spacing.LG),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            height=340,
        )

        self.content = ft.Column(
            [
                metric_cards,
                ft.Container(height=Theme.Spacing.LG),
                H3Text(f"Cumulative revenue — last {self._REVENUE_WINDOW_DAYS} days"),
                ft.Container(height=Theme.Spacing.SM),
                self._chart_container,
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

        page.run_task(self._load_revenue)

    async def _load_revenue(self) -> None:
        """Fetch the timeseries and swap in the teal line chart."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(
            "/api/v1/payment/revenue-timeseries",
            params={"days": self._REVENUE_WINDOW_DAYS},
        )
        if not isinstance(data, dict):
            self._chart_container.content = self._empty_state("Could not load chart.")
            self._refresh_chart()
            return

        points = data.get("points", [])
        if not points or all(p["amount_cents"] == 0 for p in points):
            self._chart_container.content = self._empty_state(
                f"No revenue yet in the last {self._REVENUE_WINDOW_DAYS} days"
            )
            self._refresh_chart()
            return

        self._chart_container.content = self._build_chart(points)
        self._refresh_chart()

    def _refresh_chart(self) -> None:
        if self.page:
            self._chart_container.update()

    @staticmethod
    def _empty_state(message: str) -> ft.Control:
        return ft.Row(
            [SecondaryText(message)],
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _build_chart(self, points: list[dict[str, Any]]) -> ft.Control:
        """Render a teal-stroked cumulative-revenue area chart.

        The daily series from the endpoint is summed into a running total
        client-side so the line reads as continuous growth (monotonically
        non-decreasing) rather than noisy day-over-day spikes. Empty days
        simply carry the prior day's total forward.
        """
        teal = styles.PulseColors.TEAL
        running = 0.0
        dollars: list[float] = []
        for p in points:
            running += p["amount_cents"] / 100.0
            dollars.append(running)
        max_y = dollars[-1] if dollars else 0.0
        # Round the y-axis ceiling up so the top label isn't flush against
        # the curve's final point.
        y_max = max(10.0, max_y * 1.15)

        data_points = [
            ft.LineChartDataPoint(x=float(i), y=dollars[i]) for i in range(len(dollars))
        ]
        series = ft.LineChartData(
            data_points=data_points,
            stroke_width=2,
            color=teal,
            curved=True,
            stroke_cap_round=True,
            below_line_bgcolor=ft.Colors.with_opacity(0.15, teal),
            below_line_cutoff_y=0.0,
            point=False,
        )

        # Label the first, middle, and last x-ticks only — one per week is
        # too noisy on a 30-day window.
        tick_idxs = {0, len(points) // 2, len(points) - 1}
        x_labels = [
            ft.ChartAxisLabel(
                value=float(i),
                label=ft.Text(
                    _short_date(points[i]["date"]),
                    size=10,
                    color=styles.PulseColors.MUTED,
                ),
            )
            for i in tick_idxs
            if 0 <= i < len(points)
        ]

        return ft.LineChart(
            data_series=[series],
            border=ft.Border(
                bottom=ft.BorderSide(1, styles.PulseColors.BORDER),
                left=ft.BorderSide(1, styles.PulseColors.BORDER),
            ),
            horizontal_grid_lines=ft.ChartGridLines(
                interval=y_max / 4 if y_max else 1,
                color=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                width=1,
            ),
            left_axis=ft.ChartAxis(
                labels=[
                    ft.ChartAxisLabel(
                        value=v,
                        label=ft.Text(
                            f"${v:,.0f}",
                            size=10,
                            color=styles.PulseColors.MUTED,
                        ),
                    )
                    for v in (0.0, y_max / 2, y_max)
                ],
                labels_size=40,
            ),
            bottom_axis=ft.ChartAxis(labels=x_labels, labels_size=20),
            min_y=0.0,
            max_y=y_max,
            min_x=0.0,
            max_x=float(len(points) - 1),
            animate=500,
            expand=True,
        )


def _short_date(iso: str) -> str:
    """Render ``2026-04-22`` as ``Apr 22``."""
    try:
        return datetime.fromisoformat(iso).strftime("%b %d")
    except ValueError:
        return iso


# =============================================================================
# Settings Tab
# =============================================================================


class SettingsTab(ft.Container):
    """Provider configuration and health details."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}

        provider = metadata.get("provider_display_name", "Unknown")
        is_test = metadata.get("is_test_mode", True)
        healthy = metadata.get("healthy", False)
        api_version = metadata.get("api_version") or "Unknown"
        health_msg = metadata.get("health_message", "") or ""
        # ProviderHealth.is_test_mode defaults to True, so when a
        # provider isn't configured (e.g. STRIPE_SECRET_KEY unset →
        # health_check returns early without populating is_test_mode)
        # the modal would render "Test Mode" alongside the "not
        # configured" detail line, which reads as "half working"
        # instead of "nothing wired up." Detect the unconfigured combo
        # from the health message and surface "Not Configured" instead.
        # The proper fix is making is_test_mode tri-state on the schema,
        # but this UI-side guard is the minimal correct read.
        if not healthy and "not configured" in health_msg.lower():
            mode_text = "Not Configured"
        else:
            mode_text = "Test Mode" if is_test else "Live Mode"
        status_text = "Connected" if healthy else "Disconnected"

        provider_stats: dict[str, str] = {
            "Provider": provider,
            "Mode": mode_text,
            "Status": status_text,
            "API Version": str(api_version),
        }
        if health_msg and not healthy:
            provider_stats["Details"] = health_msg

        self.content = ft.Column(
            [
                StatRowsSection(title="Provider Configuration", stats=provider_stats),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True


# =============================================================================
# Transactions Tab
# =============================================================================


class TransactionsTab(ft.Container):
    """Recent transactions with status tags."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}
        txns: list[dict[str, Any]] = metadata.get("recent_transactions", []) or []

        columns = [
            DataTableColumn("ID", width=60),
            DataTableColumn("Type", width=110),
            DataTableColumn("Status", width=140),
            DataTableColumn("Amount", width=110, alignment="right"),
            DataTableColumn("Provider ID"),
            DataTableColumn("Created", width=140),
            DataTableColumn("", width=48),  # actions
        ]

        rows: list[list[ft.Control]] = []
        for t in txns:
            status = t.get("status", "")
            status_color = _TRANSACTION_STATUS_COLORS.get(status, Theme.Colors.INFO)
            action_cell = self._build_action_cell(t)
            rows.append(
                [
                    TableNameText(str(t.get("id", ""))),
                    TableCellText(t.get("type", "")),
                    ft.Row(
                        [Tag(status, color=status_color)],
                        tight=True,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    TableCellText(
                        _fmt_amount(t.get("amount", 0), t.get("currency", "usd"))
                    ),
                    TableCellText(t.get("provider_transaction_id", "")),
                    TableCellText(_fmt_datetime(t.get("created_at"))),
                    action_cell,
                ]
            )

        body: ft.Control
        if rows:
            body = DataTable(
                columns=columns,
                rows=rows,
                row_padding=8,
                empty_message="No transactions yet",
            )
        else:
            body = EmptyStatePlaceholder(
                message="No transactions yet. Run a test checkout to see activity here."
            )

        self.content = ft.Column(
            [
                SecondaryText(
                    f"10 most recent transactions. Use `{settings.PROJECT_NAME} "
                    "payment transactions` or the REST API for full history."
                ),
                ft.Container(height=Theme.Spacing.SM),
                body,
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

    def _build_action_cell(self, txn: dict[str, Any]) -> ft.Control:
        """Row-level action menu. Refund button for refundable charges."""
        refundable = (
            txn.get("type") in _REFUNDABLE_TYPES
            and txn.get("status") in _REFUNDABLE_STATUSES
        )
        if not refundable:
            return ft.Container(width=24)

        captured = txn

        async def handle_refund_click() -> None:
            self._open_refund_dialog(captured)

        return BaseIconButton(
            on_click_callable=handle_refund_click,
            icon=ft.Icons.CURRENCY_EXCHANGE,
            tooltip="Refund",
        )

    def _open_refund_dialog(self, txn: dict[str, Any]) -> None:
        """Open a dialog to issue a refund for a transaction."""
        page = self.page
        if not page:
            return

        txn_id = txn["id"]
        original_amount_cents: int = txn.get("amount", 0)
        currency: str = (txn.get("currency") or "usd").upper()
        original_amount_display = f"{original_amount_cents / 100:,.2f}"

        amount_field = FormTextField(
            label=f"Amount ({currency})",
            value=original_amount_display,
            hint=(
                f"Leave at {original_amount_display} for full refund, "
                "or lower for partial"
            ),
            width=280,
        )
        reason_field = FormDropdown(
            label="Reason",
            options=[(value, RefundReason.LABELS[value]) for value in RefundReason.ALL],
            value=RefundReason.DEFAULT,
            width=360,
        )
        dialog_holder: dict[str, ft.AlertDialog] = {}

        async def close_dialog() -> None:
            page.close(dialog_holder["dialog"])

        async def do_refund() -> None:
            await close_dialog()

            amount_cents: int | None = None
            raw_amount = amount_field.value.strip()
            if raw_amount:
                try:
                    parsed = float(raw_amount)
                    amount_cents = int(round(parsed * 100))
                    if amount_cents >= original_amount_cents:
                        amount_cents = None  # treat as full refund
                except ValueError:
                    page.open(
                        ft.SnackBar(
                            content=ft.Text("Invalid amount"),
                            bgcolor=Theme.Colors.ERROR,
                        )
                    )
                    return

            payload: dict[str, Any] = {
                "reason": reason_field.value or RefundReason.DEFAULT,
            }
            if amount_cents is not None:
                payload["amount"] = amount_cents

            from app.components.frontend.controls.snack_bar import (
                ErrorSnackBar,
                SuccessSnackBar,
            )
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(page).api_client
            status, body = await api.request_with_status(
                "POST",
                f"/api/v1/payment/refund/{txn_id}",
                json=payload,
            )

            if status == 200:
                # Invalidate so the next dashboard refresh shows updated status.
                try:
                    from app.services.payment.health import (
                        invalidate_payment_health_cache,
                    )

                    invalidate_payment_health_cache()
                except Exception:
                    pass

                SuccessSnackBar(
                    f"Refund issued for transaction #{txn_id}. "
                    "Dashboard will update on next refresh."
                ).launch(page)
            elif status == 404:
                ErrorSnackBar("Transaction not found.").launch(page)
            else:
                detail = (
                    body.get("detail")
                    if isinstance(body, dict) and body.get("detail")
                    else f"status {status}"
                )
                ErrorSnackBar(f"Refund failed: {detail}").launch(page)

        dialog = ft.AlertDialog(
            modal=True,
            title=H3Text(f"Refund transaction #{txn_id}"),
            content=ft.Column(
                [
                    BodyText(f"Original amount: {original_amount_display} {currency}"),
                    ft.Container(height=Theme.Spacing.MD),
                    amount_field,
                    ft.Container(height=Theme.Spacing.SM),
                    reason_field,
                ],
                tight=True,
                width=420,
            ),
            actions=[
                PulseButton(
                    on_click_callable=close_dialog,
                    text="Cancel",
                    variant="muted",
                ),
                PulseButton(
                    on_click_callable=do_refund,
                    text="Issue Refund",
                    variant="amber",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )
        dialog_holder["dialog"] = dialog
        page.open(dialog)


# =============================================================================
# Subscriptions Tab
# =============================================================================


class SubscriptionsTab(ft.Container):
    """Active subscriptions with billing period."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}
        subs: list[dict[str, Any]] = metadata.get("recent_subscriptions", []) or []

        columns = [
            DataTableColumn("ID", width=60),
            DataTableColumn("Customer", width=200),
            DataTableColumn("Plan", width=180),
            DataTableColumn("Status", width=140),
            DataTableColumn("Last activity", width=150),
            DataTableColumn("Provider ID"),
        ]

        rows: list[list[ft.Control]] = []
        for s in subs:
            status = s.get("status", "")
            status_color = _SUBSCRIPTION_STATUS_COLORS.get(status, Theme.Colors.INFO)
            cancel_note = ""
            if s.get("cancel_at_period_end"):
                cancel_note = " (cancels at period end)"
            # Prefer the customer's name; fall back to their email; and
            # only show an em-dash when neither is present (e.g. the sub
            # predates customer linking).
            customer_display = s.get("customer_name") or s.get("customer_email") or "—"
            rows.append(
                [
                    TableNameText(str(s.get("id", ""))),
                    TableCellText(customer_display),
                    TableNameText(f"{s.get('plan_name', '')}{cancel_note}"),
                    ft.Row(
                        [Tag(status, color=status_color)],
                        tight=True,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    TableCellText(_fmt_datetime(s.get("updated_at"))),
                    TableCellText(s.get("provider_subscription_id", "")),
                ]
            )

        body: ft.Control
        if rows:
            body = DataTable(
                columns=columns,
                rows=rows,
                row_padding=8,
                empty_message="No subscriptions",
            )
        else:
            body = EmptyStatePlaceholder(
                message="No subscriptions. Start a recurring checkout to see one here."
            )

        self.content = ft.Column(
            [body],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True


# =============================================================================
# Disputes Tab
# =============================================================================


class DisputesTab(ft.Container):
    """Chargebacks and early fraud warnings with evidence deadlines."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}
        disputes: list[dict[str, Any]] = metadata.get("recent_disputes", []) or []
        open_count = metadata.get("open_disputes", 0)

        columns = [
            DataTableColumn("ID", width=60),
            DataTableColumn("Txn", width=60),
            DataTableColumn("Status", width=160),
            DataTableColumn("Reason", width=160),
            DataTableColumn("Amount", width=110, alignment="right"),
            DataTableColumn("Evidence Due", width=130),
            DataTableColumn("Provider ID"),
        ]

        rows: list[list[ft.Control]] = []
        for d in disputes:
            status = d.get("status", "")
            status_color = _DISPUTE_STATUS_COLORS.get(status, Theme.Colors.INFO)
            rows.append(
                [
                    TableNameText(str(d.get("id", ""))),
                    TableCellText(str(d.get("transaction_id", ""))),
                    ft.Row(
                        [Tag(status, color=status_color)],
                        tight=True,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    TableCellText(d.get("reason") or "—"),
                    TableCellText(
                        _fmt_amount(d.get("amount", 0), d.get("currency", "usd"))
                    ),
                    TableCellText(_fmt_date(d.get("evidence_due_by"))),
                    TableCellText(d.get("provider_dispute_id", "")),
                ]
            )

        body: ft.Control
        if rows:
            body = DataTable(
                columns=columns,
                rows=rows,
                row_padding=8,
                empty_message="No disputes",
            )
        else:
            body = EmptyStatePlaceholder(
                message=(
                    "No disputes. Trigger one with "
                    "`stripe trigger charge.dispute.created`."
                )
            )

        header_text = (
            f"{open_count} open " if open_count else "No open "
        ) + "dispute(s). Respond to chargebacks via the Stripe dashboard."
        header_color = Theme.Colors.ERROR if open_count else Theme.Colors.SUCCESS

        self.content = ft.Column(
            [
                ft.Text(
                    header_text,
                    size=Theme.Typography.BODY,
                    color=header_color,
                    weight=ft.FontWeight.W_500,
                ),
                ft.Container(height=Theme.Spacing.SM),
                body,
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True


# =============================================================================
# Actions Tab
# =============================================================================


class ActionsTab(ft.Container):
    """Create new checkout sessions (one-time payments or subscriptions).

    Submits to POST /api/v1/payment/checkout with the form values. On success
    surfaces the checkout_url so you can open the Stripe-hosted page in a
    new tab or copy it to share/use elsewhere.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        self._catalog_entries: list[dict[str, Any]] = []

        # Price dropdown — populated async from GET /payment/catalog. Starts
        # with a single "loading" placeholder so the field has a stable
        # shape before the catalog call resolves.
        self._price_id = FormDropdown(
            label="Price (required)",
            options=[("", "Loading catalog…")],
            disabled=True,
        )
        self._mode = ft.RadioGroup(
            value="payment",
            content=ft.Row(
                [
                    ft.Radio(value="payment", label="One-time payment"),
                    ft.Container(width=Theme.Spacing.LG),
                    ft.Radio(value="subscription", label="Subscription"),
                ],
            ),
            on_change=self._on_mode_changed,
        )
        self._quantity = FormTextField(
            label="Quantity",
            value="1",
            hint="Usually 1",
            width=160,
        )
        self._success_url = FormTextField(
            label="Success URL (optional)",
            hint="Defaults to PAYMENT_SUCCESS_URL setting",
        )
        self._cancel_url = FormTextField(
            label="Cancel URL (optional)",
            hint="Defaults to PAYMENT_CANCEL_URL setting",
        )

        # Result display (hidden until we have a checkout_url).
        self._result_container = ft.Container(visible=False)

        # Submit button — pass the async handler directly. The
        # ``_on_create_clicked`` wrapper that called ``page.run_task`` is
        # gone; ``BaseElevatedButton`` awaits async callables natively.
        submit_button = PulseButton(
            on_click_callable=self._create_checkout,
            text="Create checkout session",
            variant="teal",
        )

        # Left column holds the form inputs; right column holds the submit
        # action and the returned checkout result. Stored as instance refs
        # so the async catalog-load callback can swap the dropdown in place
        # without re-indexing into nested control lists.
        self._form_column = ft.Column(
            [
                SecondaryText(
                    "Create a new Stripe checkout session. The returned "
                    "checkout_url is what you'd redirect a real customer to."
                ),
                ft.Container(height=Theme.Spacing.LG),
                self._price_id,
                ft.Container(height=Theme.Spacing.MD),
                LabelText("Mode"),
                ft.Container(height=4),
                self._mode,
                ft.Container(height=Theme.Spacing.MD),
                self._quantity,
                ft.Container(height=Theme.Spacing.MD),
                self._success_url,
                ft.Container(height=Theme.Spacing.MD),
                self._cancel_url,
                ft.Container(height=Theme.Spacing.LG),
                ft.Row([submit_button], alignment=ft.MainAxisAlignment.END),
            ],
            spacing=0,
            # 3:2 ratio with the action column so the form gets the bulk of
            # the room but the action side always stays visible no matter
            # how narrow the modal is resized.
            expand=3,
            scroll=ft.ScrollMode.AUTO,
        )

        action_column = ft.Column(
            [self._result_container],
            spacing=0,
            expand=2,
            scroll=ft.ScrollMode.AUTO,
        )

        self.content = ft.Row(
            [
                self._form_column,
                ft.Container(width=Theme.Spacing.LG),
                action_column,
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

        # Kick off the catalog fetch so the dropdown is populated by the
        # time the user looks at it. Runs on the page's task loop so the
        # modal open isn't blocked by a Stripe round-trip.
        page.run_task(self._load_catalog)

    async def _load_catalog(self) -> None:
        """Fetch active prices and rebuild the dropdown options."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/payment/catalog")
        if not isinstance(data, dict):
            self._price_id.set_error("Failed to load catalog.")
            return

        entries = data.get("entries", [])
        self._catalog_entries = entries

        if not entries:
            self._price_id = FormDropdown(
                label="Price (required)",
                options=[("", "No active prices in Stripe")],
                disabled=True,
            )
        else:
            options = [(e["price_id"], self._format_catalog_label(e)) for e in entries]
            self._price_id = FormDropdown(
                label="Price (required)",
                options=options,
            )
        # Replace the placeholder in the form column with the populated
        # dropdown. Position 2 matches the order set in __init__:
        # SecondaryText, spacer, dropdown, ...
        self._form_column.controls[2] = self._price_id
        if self.page:
            self.update()

    @staticmethod
    def _format_catalog_label(entry: dict[str, Any]) -> str:
        """Render a catalog row as ``Pro Plan — $10.00 USD / month``."""
        dollars = f"${entry['amount'] / 100:,.2f}"
        currency = entry.get("currency", "usd").upper()
        interval = entry.get("interval")
        suffix = f" / {interval}" if interval else ""
        return f"{entry['product_name']} — {dollars} {currency}{suffix}"

    def _on_mode_changed(self, e: ft.ControlEvent) -> None:
        """Lock quantity to 1 when subscription mode is selected.

        Stripe's per-seat pricing DOES support quantity > 1 on subs, but
        for the default generated project that pattern is a footgun —
        users almost always mean "one subscription" and a larger number
        just inflates the charge. Server-side the same rule is enforced
        by ``CheckoutRequest._enforce_subscription_quantity`` so an API
        caller can't sneak past by bypassing the UI.
        """
        is_sub = self._mode.value == "subscription"
        quantity_field = self._quantity._text_field
        if is_sub:
            quantity_field.value = "1"
            quantity_field.disabled = True
        else:
            quantity_field.disabled = False
        if self.page:
            quantity_field.update()

    async def _create_checkout(self) -> None:
        page = self.page
        if not page:
            return

        price_id = self._price_id.value.strip()
        if not price_id:
            self._price_id.set_error("Select a price")
            return
        self._price_id.set_error(None)

        try:
            quantity = int(self._quantity.value.strip() or "1")
            if quantity < 1:
                raise ValueError
        except ValueError:
            self._quantity.set_error("Must be a positive integer")
            return
        self._quantity.set_error(None)

        payload: dict[str, Any] = {
            "price_id": price_id,
            "mode": self._mode.value or "payment",
            "quantity": quantity,
        }
        success_url = self._success_url.value.strip()
        if success_url:
            payload["success_url"] = success_url
        cancel_url = self._cancel_url.value.strip()
        if cancel_url:
            payload["cancel_url"] = cancel_url

        from app.components.frontend.controls.snack_bar import ErrorSnackBar
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(page).api_client
        status, body = await api.request_with_status(
            "POST", "/api/v1/payment/checkout", json=payload
        )

        if status == 200 and isinstance(body, dict):
            self._render_success(body)
        else:
            detail = (
                body.get("detail")
                if isinstance(body, dict) and body.get("detail")
                else f"status {status}"
            )
            ErrorSnackBar(f"Checkout failed: {detail}").launch(page)

    def _render_success(self, data: dict[str, Any]) -> None:
        """Replace the result container with the checkout_url affordances."""
        page = self.page
        session_id = data.get("session_id", "")
        checkout_url = data.get("checkout_url", "")

        async def open_checkout() -> None:
            if checkout_url and page:
                page.launch_url(checkout_url)

        async def copy_url() -> None:
            if page and checkout_url:
                page.set_clipboard(checkout_url)
                from app.components.frontend.controls.snack_bar import (
                    SuccessSnackBar,
                )

                SuccessSnackBar("Checkout URL copied").launch(page)

        self._result_container.content = ft.Container(
            padding=ft.padding.all(Theme.Spacing.MD),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            content=ft.Column(
                [
                    H3Text("Checkout session created"),
                    ft.Container(height=Theme.Spacing.SM),
                    LabelText("session_id"),
                    BodyText(session_id),
                    ft.Container(height=Theme.Spacing.SM),
                    LabelText("checkout_url"),
                    ft.Container(
                        # Clickable URL rendered as a link. ``ink=True``
                        # gives a visible ripple confirming the click; the
                        # teal + underline cue signals tappability since
                        # selectable text can't also carry on_click in Flet.
                        content=ft.Text(
                            checkout_url,
                            size=Theme.Typography.BODY_SMALL,
                            color=styles.PulseColors.TEAL,
                            weight=ft.FontWeight.W_500,
                            style=ft.TextStyle(
                                decoration=ft.TextDecoration.UNDERLINE,
                            ),
                        ),
                        on_click=lambda _: open_checkout(),
                        ink=True,
                        tooltip="Open checkout in browser",
                    ),
                    ft.Container(height=Theme.Spacing.MD),
                    ft.Row(
                        [
                            PulseButton(
                                on_click_callable=open_checkout,
                                text="Open in browser",
                                variant="teal",
                            ),
                            ft.Container(width=Theme.Spacing.SM),
                            PulseButton(
                                on_click_callable=copy_url,
                                text="Copy URL",
                                variant="muted",
                            ),
                        ],
                    ),
                ],
                tight=True,
            ),
        )
        self._result_container.visible = True
        if page:
            self._result_container.update()


# =============================================================================
# Root modal
# =============================================================================


class PaymentDetailDialog(BaseDetailPopup):
    """Detail modal for the payment service."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        subtitle = metadata.get("provider_display_name", "Stripe")

        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Overview", content=OverviewTab(component_data, page)),
                ft.Tab(
                    text="Transactions",
                    content=TransactionsTab(component_data, page),
                ),
                ft.Tab(
                    text="Subscriptions",
                    content=SubscriptionsTab(component_data, page),
                ),
                ft.Tab(
                    text="Disputes",
                    content=DisputesTab(component_data, page),
                ),
                ft.Tab(
                    text="Actions",
                    content=ActionsTab(component_data, page),
                ),
                ft.Tab(
                    text="Settings",
                    content=SettingsTab(component_data, page),
                ),
            ],
            expand=True,
        )

        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_payment"),
            subtitle_text=subtitle,
            sections=[tabs],
            scrollable=False,
            width=1280,
            height=840,
            status_detail=get_status_detail(component_data),
        )
