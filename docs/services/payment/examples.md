# Examples

Real-world usage patterns for the Payment Service.

## One-time Payment

Sell a single product for a fixed price. The user clicks "Buy", gets redirected to Stripe Checkout, pays, and comes back to a success page.

### Stripe dashboard setup

1. **Products → Add product**, name it ("Premium eBook", "Pro License", etc.).
2. Under pricing, choose **One off** (not recurring).
3. Set the amount (e.g. `$29.00 USD`).
4. Save and copy the Price ID. It looks like `price_1ABC...`.

### Backend: trigger checkout

```python
import httpx

async def start_checkout(price_id: str) -> str:
    """Create a checkout session and return the redirect URL."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/payment/checkout",
            json={
                "price_id": price_id,
                "mode": "payment",
                # success_url and cancel_url are optional here; when omitted
                # they fall back to PAYMENT_SUCCESS_URL / PAYMENT_CANCEL_URL
                # settings, which default to the bundled pages at
                # /payment/success and /payment/cancel. Override by passing
                # explicit values below.
            },
        )
        response.raise_for_status()
        return response.json()["checkout_url"]
```

### Frontend: redirect the user

```python
# In a Flet button handler
async def on_buy_clicked(e: ft.ControlEvent) -> None:
    checkout_url = await start_checkout("price_1ABC...")
    e.page.launch_url(checkout_url)
```

### Confirming payment

By default, after a successful charge Stripe redirects the user to the bundled page at `/payment/success?session_id=cs_test_...`. It's styled to match the Aegis palette and works with no extra wiring.

To replace that page with your own UX (e.g., to look up the transaction and show a confirmation number), set `PAYMENT_SUCCESS_URL` in `.env` to your own route and add a handler like:

```python
@app.get("/thanks")
async def payment_success(session_id: str, db: AsyncSession = Depends(get_async_db)):
    service = PaymentService(db)
    # Transaction is populated by the webhook handler;
    # this page may show a loading state until it arrives.
    txn = await service.get_transaction_by_session_id(session_id)
    if txn and txn.status == "succeeded":
        return {"status": "confirmed", "amount": txn.amount}
    return {"status": "processing"}
```

The canonical source of truth is the webhook, not the redirect. Users can close the tab before redirecting, but Stripe will always send the `checkout.session.completed` event, so business-critical logic (granting access, sending receipts) should live in the webhook handler, not the success page.

## Subscription

Recurring billing for monthly or yearly plans.

### Stripe dashboard setup

1. **Products → Add product**.
2. Choose **Recurring** pricing.
3. Set the billing period (monthly, yearly) and amount.
4. Copy the Price ID.

### Trigger checkout with subscription mode

The only difference from one-time payments is `"mode": "subscription"`:

```python
await client.post(
    "http://localhost:8000/api/v1/payment/checkout",
    json={
        "price_id": "price_recurring_ABC...",
        "mode": "subscription",
    },
)
```

!!! warning "Mode must match price type"
    Sending `mode: "payment"` with a recurring price (or vice versa) returns a `400` with Stripe's error: `"You specified 'payment' mode but passed a recurring price."` Always match the mode to the Price configuration.

### Listing active subscriptions

```bash
curl "http://localhost:8000/api/v1/payment/subscriptions?status=active"
```

### Cancelling at period end

```python
async def cancel_user_subscription(db: AsyncSession, subscription_id: int) -> None:
    await client.post(
        f"http://localhost:8000/api/v1/payment/subscriptions/{subscription_id}/cancel"
    )
```

The subscription keeps billing until `current_period_end`, then Stripe stops. The local record sets `cancel_at_period_end=true` so your UI can display "Cancels on April 30".

## Refunding a Charge

Full refund:

```bash
curl -X POST http://localhost:8000/api/v1/payment/refund/42 \
  -H "Content-Type: application/json" \
  -d '{"reason": "requested_by_customer"}'
```

Partial refund (amount in cents):

```bash
curl -X POST http://localhost:8000/api/v1/payment/refund/42 \
  -H "Content-Type: application/json" \
  -d '{"amount": 500, "reason": "requested_by_customer"}'
```

The refund creates a separate `payment_transaction` record of `type="refund"` linked to the original charge. The original transaction's status becomes `refunded` or `partially_refunded`.

## Listening to Webhook Events Locally

Open two terminals:

```bash
# Terminal 1: start the webserver
make serve
```

```bash
# Terminal 2: forward Stripe events to the webserver
my-app payment webhook
```

Copy the `whsec_...` printed by `stripe listen` into `.env` as `STRIPE_WEBHOOK_SECRET`, then restart the webserver. Now real Stripe events (and synthetic ones via `stripe trigger <event>`) flow to your local handler.

### Triggering specific events

In a third terminal, fire any handled event directly. This is useful for testing code paths without running a full checkout:

```bash
stripe trigger checkout.session.completed
stripe trigger payment_intent.succeeded
stripe trigger invoice.payment_failed
stripe trigger customer.subscription.deleted
stripe trigger charge.refunded
```

## Handling Fraud and Disputes

Even with Stripe Radar, some fraud slips through as chargebacks. The payment service tracks the full lifecycle in a `payment_dispute` table so you can react in code.

### Events the service handles automatically

| Event | What happens |
|-------|--------------|
| `radar.early_fraud_warning.created` | New `payment_dispute` row with status `warning_issued`. Chargeback is usually 1-30 days away; this is your window to refund proactively and avoid the dispute fee. |
| `charge.dispute.created` | New `payment_dispute` row with status `needs_response`. `evidence_due_by` is set to your response deadline. |
| `charge.dispute.updated` | Existing row updated (status, evidence deadline, reason). |
| `charge.dispute.closed` | Row updated to `won`, `lost`, `charge_refunded`, or `warning_closed`. |

### Reacting to an early fraud warning

The standard play is to refund proactively before the chargeback lands. Fighting a chargeback costs ~$15 per dispute plus reputation damage; proactive refunds cost you only the original amount.

```python
from app.services.payment.constants import DisputeStatus
from app.services.payment.payment_service import PaymentService

class FraudAwarePaymentService(PaymentService):
    async def _handle_early_fraud_warning(self, event) -> None:
        # Let the base class record the warning in the DB
        await super()._handle_early_fraud_warning(event)

        # Then revoke the user's access and issue a refund
        charge_id = event.data.get("charge", "")
        txn = await self._find_transaction_by_charge_id(charge_id)
        if not txn:
            return

        await self._revoke_access_for_charge(txn)
        await self.refund_transaction(
            transaction_id=txn.id,
            reason="Early fraud warning received",
        )
```

### Querying open disputes

List disputes that need attention (from the CLI, an admin page, or a cron job):

```bash
curl "http://localhost:8000/api/v1/payment/disputes?status=open"
```

Or in code:

```python
service = PaymentService(db)
open_disputes = await service.get_disputes(status="open")
for d in open_disputes:
    if d.evidence_due_by and d.evidence_due_by < datetime.now():
        logger.error(
            "Dispute %s evidence deadline passed without response!",
            d.provider_dispute_id,
        )
```

### Submitting evidence for a chargeback

The service records disputes but doesn't submit evidence for you; that's a manual step via the Stripe dashboard for most projects. If you want to automate it, use the Stripe API directly:

```python
import stripe

stripe.Dispute.modify(
    "dp_test_abc",
    evidence={
        "customer_email_address": "customer@example.com",
        "customer_name": "Jane Doe",
        "receipt": "https://yourapp.com/receipts/42",
        "service_date": "2026-04-01",
        "uncategorized_text": "Customer received the product. See attached delivery confirmation.",
    },
    submit=True,
)
```

This moves the dispute from `needs_response` to `under_review` on Stripe's side; the `charge.dispute.updated` webhook will then arrive and sync your local row.

### What not to build

- **Don't write your own fraud scoring** on top of Radar. Stripe has a billion-transaction model; you won't beat them. Your job is to react to their signal, not re-derive it.
- **Don't auto-submit evidence** without human review for low-volume projects. False positives (you submitting evidence on a legitimate dispute) get you flagged by card networks.

## Extending Webhook Handling

The default webhook handler persists common events to the database. To add custom application logic (send a welcome email on first payment, grant a feature flag on subscription start, etc.), override the specific event handler rather than the top-level `handle_webhook`. Each `_handle_*` method receives the full `WebhookEvent` with the original Stripe payload, while `handle_webhook` returns only a small acknowledgement dict.

```python
# In your own application code, subclass PaymentService and replace
# the _get_provider path so this subclass is used.

class MyPaymentService(PaymentService):
    async def _handle_checkout_completed(self, event) -> None:
        # Persist the transaction first via the base class
        await super()._handle_checkout_completed(event)

        # Then your side effects, using fields from event.data directly
        session_id = event.data.get("id", "")
        customer_id = event.data.get("customer")
        if customer_id:
            await self._grant_premium_access(customer_id)
        await self._send_receipt_email(session_id)
```

If you need to fan out on event type in one place instead of overriding each handler, subclass `_process_event`:

```python
async def _process_event(self, event) -> None:
    await super()._process_event(event)

    if event.event_type == "customer.subscription.created":
        await self._announce_new_subscriber(event.data)
```

Both patterns keep the base-class persistence and dispatch intact.

## Adding a New Payment Provider

The service is designed for multi-provider support. To add Paddle, PayPal, or any other:

1. Create `app/services/payment/providers/paddle.py` (or similar) implementing `BasePaymentProvider`.
2. Register it in `PaymentService._get_provider()` based on a new `PAYMENT_PROVIDER` env var.
3. Add its env vars to `app/core/config.py` and `.env.example`.

The `BasePaymentProvider` interface is intentionally small. Five methods cover checkout, transactions, refunds, customers, and webhooks, so a new provider typically lands in a few hundred lines.
