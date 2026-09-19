"""The state the payment mixins share, and the two Stripe coercions.

Every mixin imports this module, so the timestamp and dispute-status
translations live here rather than in one of them.
"""

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    pass

from .constants import (
    DisputeStatus,
)
from .providers.base import BasePaymentProvider

logger = logging.getLogger(__name__)


def _ts_to_naive(value: int | None) -> datetime | None:
    """Convert a Stripe unix timestamp to a naive UTC datetime.

    Stripe returns all timestamps as unix ints. Our schema stores
    naive datetimes (legacy choice - most columns are
    ``timestamp without time zone``), so every conversion goes
    ``unix -> aware UTC -> drop tzinfo``. Falsy inputs (None, 0)
    return None so callers can chain with ``or`` fallbacks.
    """
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=UTC).replace(tzinfo=None)


def _stripe_dispute_status_to_local(stripe_status: str) -> str:
    """Map Stripe's dispute.status values to our DisputeStatus lifecycle.

    Stripe's values: warning_needs_response, warning_under_review, warning_closed,
    needs_response, under_review, charge_refunded, won, lost.
    Ours collapses the warning_* prefix into a single WARNING_ISSUED state
    since the distinction isn't operationally useful for most apps.
    """
    if stripe_status in ("warning_needs_response", "warning_under_review"):
        return DisputeStatus.WARNING_ISSUED
    if stripe_status == "warning_closed":
        return DisputeStatus.WARNING_CLOSED
    if stripe_status == "needs_response":
        return DisputeStatus.NEEDS_RESPONSE
    if stripe_status == "under_review":
        return DisputeStatus.UNDER_REVIEW
    if stripe_status == "won":
        return DisputeStatus.WON
    if stripe_status == "lost":
        return DisputeStatus.LOST
    if stripe_status == "charge_refunded":
        return DisputeStatus.CHARGE_REFUNDED
    return stripe_status  # Pass through unknown values rather than lose data.


class PaymentServiceBase:
    """State and cross-module calls every payment mixin relies on.

    ``PaymentService.__init__`` sets the session and the provider; the
    methods declared here live on sibling mixins or on the service
    itself. Naming them lets each module type check on its own while
    the real definitions win at runtime.
    """

    db: AsyncSession
    provider: BasePaymentProvider

    if TYPE_CHECKING:

        def get_or_create_provider(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _customer_ids_for_user(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _email_for_stripe_customer(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...
        async def _find_transaction_by_charge_id(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...
        async def _resolve_invoice_plan_name(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...
        async def _tag_with_email_result(self, *args: Any, **kwargs: Any) -> Any: ...
        async def _transaction_ids_for_customers(
            self, *args: Any, **kwargs: Any
        ) -> Any: ...
        async def get_dispute_by_id(self, *args: Any, **kwargs: Any) -> Any: ...
        async def get_disputes(self, *args: Any, **kwargs: Any) -> Any: ...
        async def get_subscriptions(self, *args: Any, **kwargs: Any) -> Any: ...
        async def get_transaction_by_id(self, *args: Any, **kwargs: Any) -> Any: ...
        async def get_transactions(self, *args: Any, **kwargs: Any) -> Any: ...
