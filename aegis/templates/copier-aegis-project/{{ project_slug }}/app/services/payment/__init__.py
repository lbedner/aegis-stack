"""Payment service: Stripe checkout, subscriptions, invoices, webhooks.

``service`` is the entry point; its logic lives in ``domains`` (charges,
subscriptions, webhooks, reporting, the catalog, customer mail), what it
talks to in ``adapters`` (the Stripe provider). The spine
is ``deps``, ``models``, ``schemas``, ``constants``, ``health``,
``seed`` (reference rows) and ``demo_seed`` (the demo ledger).
"""
