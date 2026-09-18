"""The Actions tab: create a checkout against the live catalog.

The one tab that writes. It loads the provider's catalog, builds a
session for the selected product, and renders the resulting link.
"""

from typing import Any

import flet as ft
from app.components.frontend import styles
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    LabelText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import (
    PulseButton,
)
from app.components.frontend.controls.form_fields import FormDropdown, FormTextField
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus


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
