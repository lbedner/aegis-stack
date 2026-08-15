"""Investment-activity ingestion: custodian trade ledgers (brokerage/HSA
exports), as opposed to ``import_service``'s register (bank/card) CSVs.

One profile module per source shape (``optum.py`` today; a Fidelity or
generic-columns profile is a sibling module later) parses raw text into the
shared ``InvestmentActivity`` list defined in ``activity.py``. ``loader.py``
writes that list to the database via ``FinanceService``'s existing
idempotent ``upsert_trade``/``upsert_provider_security`` methods.
"""
