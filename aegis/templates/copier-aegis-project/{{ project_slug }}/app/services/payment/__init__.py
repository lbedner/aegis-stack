"""Payment service: Stripe checkout, subscriptions, invoices, webhooks.

``service`` is the entry point. ``providers`` holds the vendor adapter,
``stripe_events`` the webhook dispatch, ``email_helpers`` and
``email_templates`` the customer mail, ``catalog`` the plans. The spine
is ``deps``, ``models``, ``schemas``, ``constants``, ``health``,
``seed`` (reference rows) and ``demo_seed`` (the demo ledger).
"""
