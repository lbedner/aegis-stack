"""The payment service's logic, a package each, its mixins composed into
``PaymentService`` on the state they share (``base``):

- ``providers``: the vendor adapter (Stripe), behind one interface
- ``charges``: refunds and disputes, money moving after a charge
- ``subscriptions``: listing, re-planning and cancelling one
- ``webhooks``: what Stripe reports (checkout, charges, invoices, the
  subscription lifecycle) and the payload shapes it reports in
- ``reporting``: revenue over time, and where the account stands
- ``catalog``: the provider's prices, cached
- ``notifications``: the email each payment event sends
"""
