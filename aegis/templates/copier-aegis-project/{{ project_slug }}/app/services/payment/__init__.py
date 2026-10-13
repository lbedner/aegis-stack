"""Payment service: Stripe checkout, subscriptions, invoices, webhooks.

``service`` is the entry point; its logic lives in ``domains`` (the vendor adapter, charges,
subscriptions, webhooks, reporting, the catalog, customer mail). The spine
is ``deps``, ``models``, ``schemas``, ``constants``, ``health``,
``seed`` (reference rows) and ``demo_seed`` (the demo ledger).
"""
