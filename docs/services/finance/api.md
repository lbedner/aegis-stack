# API Reference

Everything is under `/api/v1/finance`, grouped into sub-routers that mirror the domains. The generated project serves interactive docs at `/docs`, which is the authoritative list; this page is the map.

Every read takes the same shape of scoping: an optional owner, and an optional `account_ids` filter that narrows a response the way the dashboard's account filter narrows a tab.

## Overview

| Method | Path | Returns |
|--------|------|---------|
| GET | `/overview` | the headline figures |
| GET | `/net-worth` | the snapshot series |
| GET | `/cashflow` | income and spend by month |
| GET | `/health` | counts, freshness, connections needing action |

## Accounts

| Method | Path | Does |
|--------|------|------|
| GET | `/accounts` | list |
| PATCH | `/accounts/{id}` | rename, retype, set a balance |
| PATCH | `/accounts/{id}/secured-by` | link a loan to what it is against |
| PATCH | `/accounts/{id}/property` | property details |
| DELETE | `/accounts/{id}` | remove |
| POST | `/accounts/{id}/reconcile` | reconcile to a statement balance |
| GET | `/accounts/{id}/valuations` | the valuation series |

## Register

| Method | Path | Does |
|--------|------|------|
| GET | `/transactions` | the register, filtered and paged |
| GET | `/uncategorized` | the Review backlog |
| POST | `/transactions/{id}/split` | carve into category lines |
| DELETE | `/transactions/{id}/split` | undo the split |
| POST | `/transactions/delete` | remove rows |
| GET | `/tags` | the tag directory |
| POST | `/transactions/tags` | tag a row |
| DELETE | `/transactions/{id}/tags/{tag_id}` | untag |

## Payees and Categories

| Method | Path | Does |
|--------|------|------|
| GET | `/merchants` | payees with counts |
| PATCH | `/merchants/{id}` | rename |
| POST | `/merchants/{id}/merge` | fold one payee into another |
| POST | `/transactions/assign-merchant` | attach a payee to a row |
| GET | `/payee-groups` | groups |
| POST | `/payee-groups/assign` | add a payee to a group |
| GET | `/categories` | the tree |
| GET | `/categories/options` | flattened, for pickers |
| GET | `/spending` | spend by category |
| GET | `/spending/summary` | rollup |
| GET | `/spending/transactions` | the rows behind a slice |

## Bills and Income

| Method | Path | Does |
|--------|------|------|
| GET | `/recurring` | streams |
| POST | `/recurring/rescan` | re-run detection |
| GET | `/recurring/projection` | the forward walk |
| GET | `/recurring/review-queue` | streams awaiting a decision |
| PATCH | `/recurring/{id}` | edit amount, cadence, date |
| DELETE | `/recurring/{id}` | remove |
| POST | `/recurring/{id}/confirm` | this is real |
| POST | `/recurring/{id}/pause` · `/resume` | pause until a date |
| POST | `/recurring/{id}/mute` · `/unmute` | keep it out of the forecast |
| POST | `/recurring/{id}/attach` | this payment paid this bill |
| POST | `/recurring/categorize` | set the inherited category |
| POST | `/transactions/declare-recurring` | make a bill from selected rows |

## Budget, Envelopes and Goals

| Method | Path | Does |
|--------|------|------|
| GET | `/budget/summary` | the four buckets |
| GET | `/budget/outlook` | months ahead |
| GET | `/budget/stat-details` | the rows behind a header figure |
| GET | `/budget/suggestions` | proposed envelopes |
| POST | `/budget/suggestions/dismiss` · `/restore` | keep or drop a suggestion |
| POST | `/budget/lines` | set an envelope |
| DELETE | `/budget/lines/{id}` | remove one |
| POST | `/budget/goal` | budget toward a goal |
| GET | `/envelopes` | envelope accounts |
| PATCH · DELETE | `/envelopes/{account_id}` | edit, remove |
| POST | `/envelopes/{account_id}/credit` · `/spend` | move money in or out |
| GET | `/goals` | goals with progress |
| POST | `/goals` | create |
| PATCH · DELETE | `/goals/{account_id}` | edit, remove |
| POST | `/goals/{account_id}/contribute` | contribute |
| GET | `/goals/target-preview` | what a target implies monthly |

## Changes

The propose and approve queue.

| Method | Path | Does |
|--------|------|------|
| POST | `/changes` | file a proposal |
| GET | `/changes` | the queue |
| GET | `/changes/{id}` | one proposal |
| POST | `/changes/{id}/approve` · `/reject` | decide |
| GET | `/changes/batch/{batch_id}` | a batch |
| POST | `/changes/batch/{batch_id}/approve` · `/reject` | decide on all of it |

## Investments

| Method | Path | Does |
|--------|------|------|
| GET | `/holdings` · `/accounts/{id}/holdings` | positions |
| GET | `/trades` · `/accounts/{id}/trades` | activity |
| POST | `/import-investments` | a custodian export |

## Imports

| Method | Path | Does |
|--------|------|------|
| POST | `/import/preview` | what would happen |
| POST | `/import` | do it |
| GET | `/import/batches` | past imports |
| GET | `/import/batches/{id}` | one batch and its rows |

Uploads are capped at 10 MB.

## Connections

Present when a provider is enabled.

| Method | Path | Does |
|--------|------|------|
| GET | `/connections` | linked institutions |
| DELETE | `/connections/{id}` | unlink |
| POST | `/connections/sync` | pull now |
| POST | `/connections/{id}/relink` | re-authenticate |
| POST | `/plaid/link-token` · `/exchange` | the Plaid link flow |
| POST | `/plaid/hosted-link` · `/hosted-link/complete` | the hosted variant |
| POST | `/plaid/sync` | pull from Plaid |
| POST | `/webhook/plaid` | provider callback |
| POST | `/snaptrade/connect` · `/connect/complete` | the SnapTrade link flow |

## Insights and Analyst

| Method | Path | Does |
|--------|------|------|
| GET | `/insights` | the findings |
| POST | `/insights/{id}/dismiss` | dismiss one |
| POST | `/analyst/run` | generate the daily note now |
