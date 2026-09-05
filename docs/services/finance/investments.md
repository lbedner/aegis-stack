# Investments

Holdings, trades, and what they are worth. Investment accounts sit in the same ledger as everything else, so net worth is one number rather than two apps added together.

## What Is Tracked

| Thing | Meaning |
|-------|---------|
| **Security** | the instrument: ticker, name, type |
| **Holding** | how much of it an account holds, and at what cost |
| **Trade** | a buy, sell, dividend, or contribution |
| **Price** | a stored quote, so a valuation is reproducible |

Prices are stored rather than fetched at read time. A number on a report should mean the same thing tomorrow as it did when it was written, and a chart that silently re-prices history is not a record.

## Where the Data Comes From

Two paths, deliberately separate:

**Custodian activity files.** A brokerage or HSA export is a trade ledger, not a register, so it has its own importer path with one profile per source shape. Optum ships today; another custodian is a sibling profile rather than a fork of the CSV importer.

**Provider connections.** SnapTrade covers brokerage links where a connection is available.

Both land through the same idempotent writes, so re-importing an overlapping export updates rather than duplicates.

## Holdings and Net Worth

Net worth spans cash, liabilities and positions. Investment balances feed the same snapshot series the rest of the ledger uses, which is what lets the net-worth chart cover a portfolio and a checking account on one line.

The projection deliberately does **not** spend your positions. It walks cash, because "can I cover the month" is a question about cash, not about what you could liquidate.

## Related

| Topic | Description |
|-------|-------------|
| [Importing and Connections](imports.md) | file imports and provider links |
| [Accounts and the Register](accounts.md) | how net worth is carried over time |
| [API Reference](api.md) | holdings and trades endpoints |
