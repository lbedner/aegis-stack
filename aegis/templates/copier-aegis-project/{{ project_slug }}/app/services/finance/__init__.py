"""Finance service: account aggregation, transactions, net worth, and import.

Three questions, three folders:

- ``domains/`` - what the service KNOWS. ``ledger`` (the money facts:
  accounts, transactions, categories, merchants, transfers, net worth),
  ``planning`` (forward-looking money: budgets, goals, envelopes,
  recurring streams), ``detection`` (passes that infer what nobody typed:
  transfer pairs, rhythms, insights, and the AI analyst that narrates
  them), ``investments`` (securities, holdings, trades).
- ``adapters/`` - what it TALKS TO. ``providers`` (Plaid, SnapTrade:
  API clients plus the sync that turns a link into rows) and
  ``importers`` (CSV/OFX/QIF parsers plus the shared ingest pipeline).
- ``models/`` - the vocabulary all of the above speak, one module per
  table group.

Plus ``service/`` - the entry point: ``FinanceService``, a thin facade
every route/job/CLI goes through (injected via
``deps.get_finance_service``), one mixin per domain area.

``seeds/`` holds baseline reference rows and the demo ledger. The spine
is ``deps.py``, ``schemas.py``, ``constants.py``, ``utils.py``,
``health.py``, ``jobs.py``.

The direction of travel is one-way: domains speak models and never reach
into adapters, so a provider outage is never a domain concern.

Connectivity providers (Plaid, SnapTrade) ship behind their own copier
sub-flags; file import and manual accounts have no third-party dependency.
"""
