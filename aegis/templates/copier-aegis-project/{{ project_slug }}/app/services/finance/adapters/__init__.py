"""The finance adapters: what this service talks to.

``providers`` is the live aggregators (Plaid, SnapTrade) - API clients
plus the sync logic that turns a provider link into accounts and
transactions. ``importers`` is the file formats (OFX/QFX, QIF, CSV) and
the batch/dedup pipeline every one of them shares.

Both write the same tables the domains read, through the same models, so
a row's origin stops mattering the moment it lands.
"""
