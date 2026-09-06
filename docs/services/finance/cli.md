# CLI Commands

Every command lives under `finance` in the generated project's CLI:

```bash
my-app finance --help
```

All of them take `--owner-user-id` where ownership applies. Standalone finance is single-user, so you can usually leave it off.

## status

A quick read on the ledger: account and transaction counts, snapshot freshness, and connections needing attention.

```bash
my-app finance status
```

## accounts

```bash
my-app finance accounts list
my-app finance accounts create --help
```

Manual accounts, created and listed without the dashboard. Useful for scripting a setup, and for the accounts that will never come from a provider: a house, a private valuation.

## import

```bash
my-app finance import statement.qfx
my-app finance import export.csv --account-id 3
```

Imports an OFX, QFX, QIF or CSV file. `--account-id` pins the destination when the file does not name an account the ledger recognises.

## import-investments

```bash
my-app finance import-investments activity.csv --account-id 7 --profile optum --ticker "Vanguard 500 Index=VFIAX"
```

A custodian trade export rather than a register file. `--profile` selects the source shape. `--ticker NAME=SYMBOL` (repeatable) maps a fund's name in the export to its ticker so its trades match a known security; a fund left unmapped is imported under a placeholder `MANUAL:` ticker rather than dropped.

## sync

```bash
my-app finance sync
my-app finance sync --connection-id 2
```

Pulls from provider connections. With no `--connection-id`, syncs everything that is due.

## recompute-snapshots

```bash
my-app finance recompute-snapshots --days 35
```

Rebuilds the balance and net-worth snapshot series. Net worth is a persistence problem rather than a computation, so this is how you backfill after an import that changed history, or repair a gap left by downtime. The window is bounded so it never scans deep history by accident.

## seed-demo

```bash
my-app finance seed-demo --months 12
my-app finance seed-demo --clear
```

Fills the project with a plausible ledger so every tab has something in it: accounts, spending history, bills, a budget. `--reset` replaces existing demo data, `--clear` removes it.

## fire-webhook

```bash
my-app finance fire-webhook --connection-id 2
```

Simulates a provider webhook against a connection. For exercising the webhook path locally without waiting on a provider to send one.

## Related

| Topic | Description |
|-------|-------------|
| [Importing and Connections](imports.md) | what the import and sync commands feed |
| [API Reference](api.md) | the same operations over HTTP |
