"""The finance domains: what this service knows.

``ledger`` is the recorded past (accounts, transactions, categories,
merchants). ``planning`` is what that past implies about the future
(budgets, goals, envelopes, recurring streams). ``detection`` is the
passes that infer facts nobody typed (transfers, rhythms, insights).
``investments`` is securities and the positions held in them.

Each is function-style (``async def foo(db, ...)``) and owns its own
``queries`` module. They speak the shared vocabulary in
``finance.models``; they never reach into ``finance.adapters``, which is
what keeps a provider outage from being a domain concern.
"""
