  # Changelog

  All notable changes to this project will be documented in this file.

  The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
  and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.11.0] - 2026-09-06

### Added

- **Agents and memory modules**: the AI service gains first-class agent
  rows (system prompt, model pin, granted tools, editable from the
  dashboard and the CLI) and memory modules that are fetched into
  context before a turn, so an agent opens a conversation already
  briefed rather than spending its first turns discovering the
  situation. Documented under `docs/services/ai/` (agents, memory
  modules, providers, API, CLI).

- **Code mode**: an agent flagged `code_mode` writes one Python script
  that calls its granted tools as functions, run in a sandbox, instead
  of a chain of tool round-trips. Writes never ride the sandbox: a tool
  registered as a native write stays a visible call in the trail. The
  finance service ships host tools for it (ledger, accounts, bills,
  quotes) and a research-agent guide.

- **An embeddable chat surface**: a reusable `ChatPanel` control
  (streaming transcript, resume-latest, per-surface history, model
  picker) and its first consumer, a Chat tab in the finance modal bound
  to a seeded finance assistant. Answers carry a hover-to-copy button.
  The assistant can list its own open and recently decided cards with
  `pending()`, retract a superseded card whole with `withdraw_batch`
  and a reason the user sees, and redraw cards on request instead of
  retyping their rows; a withdrawn card reads "withdrawn", not
  "rejected".

- **Finance write surface**: agents propose ledger mutations through a
  `propose`/`propose_many` queue and nothing runs until the user
  approves. Every proposal is a `finance_pending_change` row rendered
  by one component registry on the in-chat card and the Review >
  Approvals queue; batches share one card with a per-row veto.
  Registered change types cover categorize, assign payee, tag/untag,
  split, and recurring match. Money movement is deliberately not on the
  list.

- **Finance planning surfaces**: budgets with envelopes that auto-credit
  on a schedule, goals stated as accounts (a goal can be sized in months
  of measured expenses rather than a fixed sum, resolved on read),
  net-worth history, spending summary, and a secured-debt link that
  records which property secures a liability so equity and LTV derive
  from it everywhere accounts are read.

- **Finance findings**: deterministic rules (large transaction, fee,
  overspend, price hike, missed payment) raise findings on the Review >
  Attention tab with the house severity dot and a dismiss.

- **Finance documentation**: a page per tab and per domain under
  `docs/services/finance/` (accounts, bills, projected, budget, review,
  investments, imports, chat, API, CLI), with screenshots from a demo
  household redesigned to have something to show: two earners on
  different rhythms, thin cash with the surplus invested, a carried
  card, a quarterly property tax, and a Review tab with work in it.
  `make docs-serve` resolves a free port like every other host publish.

- **Imports ask which account a statement belongs to**: a single-account
  CSV or QIF with no target no longer fails with a bare 400. The preview
  says the account is missing, the client asks, and the review dialog
  names layout and target ("Chase Credit Card layout into Amex") so a
  statement aimed at the wrong account is caught before Import.

- **Storage component**: `include_storage` adds an `S3Storage` backend
  for any S3-compatible bucket (boto3, SigV4, presigned URLs) behind the
  same `ObjectStorage` protocol the filesystem backend implements, with
  SeaweedFS in the dev compose stack, a health check, and a card and
  modal. Documented under `docs/components/storage/`.

- **Documents on the worker, with a jobs surface**: document extraction
  reads each page once (text layer where there is one, the vision model
  where there is not) and keeps the readings; with a worker in the
  stack the run is a queued job on arq, dramatiq, or taskiq alike, and
  without one it is the same in-process task as before. The generic
  jobs surface (a job record, two SSE streams, an in-process runner and
  a Redis-backed store) is documented for the next consumer. Documents
  also gained a lifecycle: supersession chains, a typed-title
  protection gate on delete, and a channel recording how the paper
  arrived. Documented under `docs/services/documents/`.

- **Init blueprints**: `aegis init` can start from a named blueprint
  (the first is `finance`) that selects the components and services a
  purpose needs, with a guided picker and a `blueprints` command to list
  them.

- **Plugins register their own CLI verbs**: a component or service spec
  declares the `aegis` subcommands it contributes, and the generic
  schema engine gates migrations on what the stack actually selected.

- **Document store service**: an optional `documents` service that keeps
  the paper an application accumulates - scans, statements, letters,
  forms - with ingest, tagging, listing, download, and soft delete.
  Documents ride the storage seam, so a row records a content-derived
  key and never a path: the same scan uploaded twice is one document and
  one object, which makes a retried upload or a scanner that runs twice
  free rather than duplicative. What a document MEANS - a case, a
  deadline, a claim it proves - is deliberately absent; that belongs to
  whatever consumes it.

- **Chat attachments outlive the turn that carried them**: images are
  stored on receipt and the message records where they went, so a
  reopened conversation still shows the screenshot it is discussing and
  a replay no longer depends on session memory still holding megabytes.
  Re-attaching the same image costs nothing (content addressing), and a
  storage failure never costs the user their message: the question still
  reaches the model, the picture is simply not kept.

- **Finance rows say whose money they describe**: a `finance_subject`
  table plus a nullable `subject_id` on accounts and recurring streams.
  Households manage money for other people (a parent in care, a child's
  savings, an estate), and with a single owner column those sat beside
  the household's own indistinguishably, so every total quietly mixed
  two people's money and "what were his resources on this date" was not
  a question anyone could ask. Null means the household's own, so every
  existing ledger and query reads exactly as before; accounts can be
  narrowed to one subject, or to the household alone.

- **Durable storage for bytes, addressed by content**: `app/core/storage.py`
  introduces the seam every future backend implements - put, get, exists,
  delete - with a filesystem backend and a named docker volume behind it.
  Keys are derived from the payload's SHA-256 rather than from a filename
  or a path (`sha256/ab/cd/<digest>`), so storing the same bytes twice is
  one object and adopting object storage later is a byte copy: the same
  key resolves identically on a disk and in a bucket, with no database
  change and no key rewriting. Callers keep the key and the backend name,
  never a path.

- **Payee assignment through the approval queue**: a
  `transaction.assign_payee` change type completes the curation write
  surface. The payload names the payee rather than an id, because the
  payee may not exist yet; approval find-or-creates it by normalized
  name, so two spellings cannot mint two rows. Batch-capable through
  `propose_many`, with the usual before/after card copy.

- **A house control for bare text inputs**: `StyledTextField` wears
  the shared input recipe as a control rather than each surface
  splicing kwargs into a raw field. The chat composer and the model
  picker's search both use it.

- **Durable readings from image turns**: attachment bytes ride one turn
  by design, but the extraction no longer dies with them. A generic
  `record_reading` chat tool (schema-forced, Pydantic-validated - the
  same door-guarding pattern as the finance queue) lets an agent record
  every line item it reads out of a receipt/order/document image; the
  turn stages it, finalize merges it into the conversation's stored
  metadata (bounded), and every later turn re-injects the recorded
  readings as context - "list the items again" works long after the
  image is gone. The finance assistant is granted the tool and
  instructed to record before answering. Reading items carry the
  source's own grouping (a shipment, a sub-receipt) so structure never
  flattens away, the assistant is forbidden from prorating category
  totals across charges, and the replayed-history budget now
  scales with the ACTIVE model's context window (5% of context in
  chars, floored at 6k for small local models, capped at 60k so a
  million-token model doesn't re-bill the whole transcript every turn;
  agent model pins respected) instead of a fixed small-model constant -
  so an agent stops "forgetting" allocations it computed minutes
  earlier.

- **Readable approval cards**: a proposal's dates read like "Aug 27,
  2026" instead of "2026-08-27" throughout the propose/approve queue
  (card, batch, and CLI-style subjects share the one formatter). Batch
  cards no longer flatten a multi-line proposal into one dot-joined
  string - each split's category and amount gets its own line, matching
  the single-card layout. Every card's plain (non-arrow) detail value
  now pops in accent teal - the same treatment an arrow's target already
  got - so the eye lands on what the proposal actually changes; a
  rejected or vetoed row never highlights. The approvals queue moved to
  its own Review > Approvals sub-tab (cards flow as a wrapping grid,
  with an empty state like every other queue); Overview now carries
  only a one-line "N pending changes awaiting your approval" banner
  that jumps straight to it - proposals are never invisible, and never
  bury the summary page.

- **Finance split transactions**: one purchase can now be carved into
  category lines. The parent row is never modified - lines live in the
  existing `finance_transaction_split` table, parts are stated as positive
  magnitudes and the unclaimed difference auto-fills as a remainder line
  under the parent's own category. Category reporting (budget actuals,
  budget summary, categories tab, spending totals, register category
  filter) swaps a split parent for its lines, while payee, cashflow and
  account math stay on the parent so nothing double-counts. Ships with
  split/unsplit API endpoints, a register split editor with a live
  remainder line, and a `transaction.split` change type on the agent
  propose/approve queue.

- **Chat image attachments**: the embeddable chat panel can attach
  images (screenshots, receipts) to a turn. Fully generic across the AI
  system: attachments ride the chat request body, the service hands them
  to the model as multimodal content (any vision-capable model on any
  provider), and history keeps a text marker of what was attached. The
  finance assistant uses this to read itemized order screenshots and
  propose a transaction split, with the approval card listing every line
  (item memo, category, amount, remainder) before anything is written.

- **Paste images anywhere on the dashboard**: Flet has no
  clipboard-image API, so a capture script spliced into the dashboard
  page posts pasted images to a new generic `/api/v1/pastebox` endpoint
  (bounded, drain-once, framework-level); consumer surfaces poll-drain
  it - chat pulls a paste straight into its attachment chips, so
  Ctrl/Cmd+V behaves exactly like the attach button. Staged chips show
  a clickable thumbnail of the actual image (full-size preview dialog),
  not just a filename. A "Receiving
  image..." busy indicator bridges the upload gap: the capture script
  announces the paste before uploading, and both the paste and picker
  paths show the same indicator until the chip lands.

- **Replay a chat message**: every user bubble (live or reloaded from
  history) carries a replay control that re-sends the same text as a
  fresh turn, riding whatever attachments are staged at that moment.
  Stored attachment markers are stripped on replay (image bytes ride
  one turn only), and a failed turn now restages its attachments
  instead of losing them - the recover-from-a-model-error path is one
  click. Sent images stay replayable from session memory (bounded to
  the last 8 image-carrying turns; never persisted), so a replay
  re-sends the original screenshots without re-pasting.

- **Agent proposal hygiene**: `transaction.split` payloads are validated
  at propose time (positive magnitudes, at least one part), so a card
  that can never execute is refused at the door and the error loops back
  to the agent. A new `withdraw` write tool lets an agent retract its
  own still-pending proposals - resolved as rejected with a "withdrawn"
  note so the audit trail keeps the mistake - instead of leaving bad
  cards for the user to reject by hand. Cards whose stored payload no
  longer passes a since-tightened rule stay resolvable: they render as
  their raw payload and can still be rejected or withdrawn (validation
  guards the door, never the cleanup). Card display rows are typed
  (`ChangeDisplayRow`) end to end through the registry, executors, and
  queue - plain dicts exist only in the frozen audit JSON and at the
  agent tool-result boundary.

### Changed

- **Add, remove, and update share one engine**: the hand-kept lists of
  shared files to regenerate are gone. A render-diff engine renders the
  template tree at the old and the new answers and three-way merges
  each shared file, with policy stated as a template-header annotation
  (user-owned, warn-if-diverged, no-backup) instead of a central table.
  Component-owned files stay declared on their own spec's `FileManifest`.

- **The AI service follows the service structure standard**: a facade
  package plus `domains/` (llm, chat, voice) in place of one
  flat directory of thirty-five modules and a 1,900-line service file.

- **The worker has one copy of each shape**: queue discovery, task
  metadata, and lifecycle hooks live once and each backend registry is
  the two answers that differ; worker health is a selector plus one
  module per backend, and a dramatiq stack that failed lint and typecheck
  unseen is clean again.

- **Forward-looking finance surfaces ask one schedule**: the projection,
  the month strip, and the budget outlook consumed their own loops and
  disagreed. `recurring/schedule.py` answers when a stream moves money,
  including overdue occurrences carried onto today; one account-scope
  rule and one read of a period's budget lines serve every surface.

- **Model vendors and labs are one thing now**: the catalog kept
  "who serves a model" and "who made it" in separate tables, which
  duplicated every organization that does both and could not say the
  two OpenAIs were the same one. A single `llm_org` table holds every
  organization, and `llm_org_role` records which hats each wears -
  maker, server, or both. A model row now carries two org references,
  `served_by_org_id` and `made_by_org_id`, and prices and deployments
  key on the org. Who made a model is resolved from the public model
  registry at sync time (following a derivative upload back to the
  weights it came from) rather than guessed from the model id, so a
  lab shipping under a new product name is picked up automatically
  and a model nobody published stays honestly unmarked.

- Generated projects default to Python 3.14. The RAG option no longer pins
  projects below 3.14 (onnxruntime now ships 3.14 wheels), so the interactive
  RAG compatibility warning is gone. Any supported version (3.11 to 3.14) can
  still be selected with `--python-version`.

### Fixed

- **`aegis update` left stale modules behind when the template moved
  them**: the removal pass compared each dropped file byte-for-byte with
  the old render, but init's post-gen step ruff-formats every file, so
  any module the formatter had touched read as "customized" and was kept.
  A 0.10.1 project updated to this release kept importable copies of the
  finance and AI packages at their old paths. Removal now looks through
  formatting the same way the sync loop does; a real edit is still kept
  and reported.
  The sync loop also compared against the unpruned template render, so
  an update from a local template checkout re-created storage, documents,
  and blog files in a project that selected none of them; both renders
  are now pruned the way init prunes before anything is compared.
- **Re-importing a statement counted every row as an edit**: an empty
  memo cell was treated as a change against a missing memo, and the demo
  seed left `original_description` empty, which no bank import does.
  Empty and missing are the same absence now, and the seed writes the
  description. Also: the import read the uploaded file before the
  server finished writing it and reported "file did not arrive"; it
  waits for the file to settle. `seed-demo --clear` removes proposals
  aimed at the transactions it deletes instead of leaving orphans.

- **Projection and budget double-counted card spend**: card-account
  streams were charged against cash and the card payment charged again;
  budget envelopes did the same. Card streams are out of the cash walk
  and a card payment suppresses the envelopes for what was spent on it,
  scoped to the cards the payment actually settles.

- **A fresh finance-plus-AI stack had several dead ends**: the reference
  seed rolled back on a fresh database, `llm status` raised on an
  ambiguous join, a fresh Ollama install showed an empty model picker
  (local tags are registered at startup and an empty catalog is never
  cached), the Review tab raised on mount from an inherited abstract
  loader, and three ranked lists clipped names to a few characters.

- **Chat writes locked SQLite**: many sequential tool calls each
  committing on their own connection raced the chat run's connection;
  SQLite now waits for a busy writer instead of failing at once, and a
  whole card withdraws in one transaction.

- **Adding a service to an existing project converges on fresh-init
  output**: a parity test diffs every file the documents service owns
  between a fresh stack and an add, and found a module no manifest
  claimed and a test shipped to stacks that could not import it. The
  `add-service ai` tests named tables and files a merged refactor had
  renamed.

- **The model picker was slow for three separate reasons**: the
  catalog ran one database query per vendor sequentially, each opening
  its own session, with the result limit applied per vendor so a
  request for 200 models fetched far more; the client awaited its
  three API calls one after another before the dialog could open; and
  every model row was built as controls up front, including inside
  collapsed groups, then rebuilt from scratch on every filter change.
  The catalog is now one query with the per-vendor fairness cap
  applied after it, the client fetches concurrently and caches for the
  session, and group rows are built on first expand.

- **Models nobody could call appeared in the picker**: the cloud
  catalog lists local-runner entries under an `ollama/` prefix, which
  is a runner namespace rather than a callable vendor. Those rows were
  filed under the local runner's own vendor and passed the "models
  this install can call" gate, so uninstallable models (and cloud
  variants needing a key the install has no concept of) were offered.
  The local runner's catalog is now owned by the local sync alone.

- **The demo dataset confirmed shopping habits as bills**: the seed
  confirmed every stream the detector found, which promoted
  discretionary rhythms (a few jittered orders a month) into
  commitments. A bill that can be missed eventually is: the household
  read as delinquent on a shopping habit the moment one gap outran the
  grace window. Only fixed-amount streams and income are confirmed now.

- **Clearing demo data left insights pointing at deleted rows**: the
  teardown released transaction back-references but not the insights
  raised about those accounts, transactions, and streams, so the stream
  foreign key refused the delete.

- **A seeding process registered no reading tool**: the fixture loader
  force-imports the modules whose tools must exist before grants are
  written, and the durable-readings module was never added, so
  `record_reading` silently got no row in any process that seeds
  without building a chat agent.

- **Overdue occurrences vanished from the balance forecast**: the
  projection fast-forwarded every stream past occurrences dated before
  today, so a day-late paycheck read as "you are $5,000 poorer for the
  next two weeks" - the walk started from a balance the check never
  reached and charged it nowhere. A stream's latest missed occurrence
  now carries to today's line (money still in flight, both directions);
  older misses stay with the insight rules' missed-payment chase, and
  one-time bills are unchanged.

- **The match picker offered nothing for income**: a candidate already
  carrying a merchant was treated as "identified as someone else", and
  paycheck deposits always arrive pre-labelled with the payroll
  processor's merchant - which never equals the human-named stream.
  Category agreement now outranks the merchant mismatch, so a deposit
  sharing the stream's own category stays offered; bills keep their
  noise protection.

- Generated projects on the AI memory backend now pass lint, typecheck and
  tests: `memory_user` and the active-model selector no longer leak into the
  memory backend, and DB-only endpoint tests are gated out.

- RAG chunking: an overlap at or above the chunk size no longer loops
  forever (default overlap is a fifth of the chunk size, larger values are
  rejected), documents that fit in one chunk are kept whole, a min chunk
  size at or above the chunk size no longer filters everything, and
  `estimate_chunks` no longer overcounts by one. The RAG service tests use
  `RAGServiceConfig` instead of a stale settings mock.

### Removed

- **The Transfers review queue**: the suggested-transfer lane
  (detection's suggest threshold, the confirm/reject endpoints and
  service methods, the Review > Transfers sub-tab, and the transfer
  response schemas) is gone end to end. Transfer detection now pairs
  ONLY high-confidence matches, automatically; a fuzzy near-miss simply
  stays visible as ordinary spend/income instead of queueing for a
  review nobody performed. Auto-pairing, category-classified flagging,
  and adjustment-pair handling are unchanged.

## [0.10.1] - 2026-07-20

### Added

- **Neon-aware deploy**: `aegis deploy` now reads the project's Postgres
  provider. For Neon projects it skips the local `pg_dump`/`psql` backup and
  rollback-restore steps and states that database backup and recovery are
  managed by Neon (branches, point-in-time restore) instead of silently
  no-opping. Localized in all nine CLI languages.
- **Orphan-proof organizations** (auth at the org level): deleting a user now
  soft-deletes any organization they solely own (a hard delete purges it,
  including its remaining invites and memberships), and a global admin can
  delete any organization. Together these guarantee an org can never be
  stranded with an unreachable owner. Cascaded deletions emit their own audit
  events alongside the user deletion.
- **Canonical brand palette**: generated apps single-source their brand
  accents in a new `BrandPalette` (teal, dark teal, amber, red). The Flet
  theme and the Pulse-style colors derive from it, fixing a drifted amber,
  and a parity test keeps the aegis CLI palette locked to the same values.
- **Finance service**: Plaid webhook tunnel auto-forwarding at startup,
  expanded connection sync, and richer account and liability API responses.

### Fixed

- **`aegis update` never silently overwrites**: files with no merge base
  (for example a service added after generation, or a failed old-template
  render) are now preserved and reported as conflicts with the template
  version written alongside as a `.rej` file, instead of being replaced with
  the template render. Files newly added by a template version are reliably
  created even when Copier fails to materialize them, so an update can no
  longer merge a new module's imports without shipping the module.
- **`aegis add`/`remove` converge on fresh-init output**: the Dockerfile
  regenerates while pristine (the htmx `css-build` stage now tracks
  add/remove htmx in both directions); stack-conditional wiring files
  (auth gates on the metrics, task-history, and load-test endpoints, CLI
  subcommand registration, scheduler job registration) regenerate instead of
  staying stale; option-gated files (auth org files, htmx auth pages, the AI
  RAG tab) are copied only when the project's configuration enables them;
  and the model-and-migration skill plus the LLM catalog API are installed
  when the first service that needs them arrives.
- **Regeneration fidelity**: ruff normalization during add/remove/update now
  runs under each file's real path so the generated project's
  per-file-ignores stay in force (`deps.py` re-export imports are no longer
  stripped), and regenerated files keep their trailing newline.
- **Generated projects lint clean**: the stack matrix now fails on any ruff
  violation in generated output (previously only a ruff crash failed it),
  and the latent violations this exposed were fixed (a duplicate blog modal
  method, an uppercase local variable in the insights collector, an unused
  variable in the finance tests).
- **AI service retrofit**: `aegis add-service ai` now ships the LLM catalog
  API, omits the RAG tab unless RAG is enabled, and a dashboard card click
  with no registered modal logs a warning naming the missing wiring instead
  of doing nothing.

## [0.10.0] - 2026-07-16

### Added

- **htmx web frontend** (`include_htmx`): an additive server-rendered web
  frontend component alongside the Flet Overseer, with a Tailwind build
  pipeline, landing page, and Docker wiring. Selection-gated like every
  component; existing stacks are untouched unless opted in.
- **SnapTrade brokerage integration for the finance service**
  (`finance_snaptrade`): a second aggregator alongside Plaid, proving the
  provider abstraction, so a SnapTrade-connected brokerage lands in the same
  tables and UI with zero schema changes. Connect portal flow, authorization
  adoption, and polling sync for accounts, positions, and activities within
  SnapTrade's polling budget. Supports both commercial keys (per-user
  registration) and personal `PERS-` keys (the key is the user; no
  registration). Securities reported by multiple aggregators merge to one
  catalog row via FIGI/CUSIP/ISIN.
- **Plaid live connectivity for the finance service** (`finance_plaid`):
  hosted-link connect flow, token exchange with AES-GCM-encrypted storage,
  account ingestion, cursor-based transactions sync, webhook handling, and a
  failure-isolated nightly sync job on the scheduler.
- **Finance categorization and insights**: internal transfer detection and
  pairing (a card payment no longer double-counts as spend),
  recurring-stream detection, and "wasting money" insights, recomputed
  post-sync and nightly; plus investment trades in the register and account
  detail.
- **Finance provider CLI commands**: `finance sync` refreshes every provider
  connection; `finance snaptrade connect` / `complete` drive the brokerage
  connect flow end to end from the terminal.
- **AI chat kit** (`app/services/ai/chat_kit`): a reusable conversation
  toolkit for generated projects (agent wrapper, token budgeting, context
  assembly, persistent history), with a TaskIQ broker for background AI
  work.
- **Agent skills**: generated projects now ship a selection-aware
  `CLAUDE.md` and `.claude/skills/` workflow skills gated by what the stack
  includes (add an endpoint, add a model and migration, add a scheduled job,
  protect an endpoint, change the stack). Skills ride
  `aegis add`/`remove`/`update`, so pre-skills projects gain them on update.
  The framework repo itself carries contributor workflow skills
  (add-service, add-component, i18n, release, template-dev) with a slimmed
  CLAUDE.md.
- **Windows-friendly dev commands**: generated projects now ship a
  `[tool.poe.tasks]` table (via `poethepoet`) covering the `Makefile`
  workflow, so `uv run poe <target>` (e.g. `uv run poe serve`, `uv run poe
  check`) can be used on Windows, where `make` isn't a native binary (after
  a one-time `uv sync --all-extras`). `make` itself is unchanged for existing
  users. The bash-only `resolve-ports.sh` / `find-free-port.sh`
  port-resolution scripts are replaced by a single Python implementation
  (`scripts/resolve_ports.py`, `scripts/dev_tasks.py`) shared by both
  interfaces.

### Changed

- **Connections tab redesign**: one card anatomy for every connection
  (collapsible, dot-style status indicators matching the rest of the
  Overseer, destructive actions behind a kebab menu), a fluid two-column
  grid, a Connect menu on the Accounts sidebar and Connections tab, and in
  sandbox mode a Plaid card with click-to-copy test credentials. The All
  Accounts register now folds investment activity in with transactions.
- **Disconnecting a provider connection is now instant**: local teardown
  happens in the request; the provider-side revoke runs after the response
  as a background task (it was always best-effort).
- **Larger default Overseer cards**: component tiles get room to render
  their metric grids cleanly at first paint. Thanks @GrCOTE7.

### Fixed

- **Second browser tab no longer renders blank**: the Overseer's route
  reentrancy guard was process-wide, so two sessions routing at the same
  instant (a second tab, a reconnect) blocked each other and the loser
  never built its view. The guard is now session-scoped.
- **Overseer modals no longer close on stray clicks**: detail popups are
  explicit-close only (backdrop click-through is opt-in), and every modal's
  Close is a themed button.
- **Finance provider syncs can no longer erase catalog data**: partial
  payloads (e.g. an activities row without pricing) update only the fields
  they carry, and the destructive SnapTrade delete-and-re-register recovery
  is gated on the specific "user already exists" error code instead of any
  failure. An undecryptable stored credential no longer blocks disconnect.

## [0.9.1] - 2026-07-12

### Added

- **Finance service (experimental)** (`aegis init --services finance`,
  `aegis add-service finance`): a personal-finance aggregator service, marked
  experimental in this release (schema, APIs, and CLI surface may change
  between releases). Ships a 33-table schema
  covering currencies and FX rates, institutions and connections (inline
  AES-GCM-encrypted credentials), accounts, liabilities, valuations, balance
  and net-worth snapshots, and a transaction ledger with splits, transfer
  pairing, and two-lane provider/import dedup. Ships file import for CSV
  (Chase and Quicken profiles), OFX/QFX, and QIF, a net-worth service, API
  endpoints, seeded demo data, and a full test suite. Optional flags gate
  Plaid (`finance_plaid`) and SnapTrade (`finance_snaptrade`) integration
  scaffolding. Requires database and scheduler; recommends worker.
- **Neon setup guide**: dedicated `components/database/neon.md` page in the
  tool docs, plus expanded database component docs.

### Fixed

- **`aegis update` no longer invents merge conflicts on pristine projects**:
  generated projects are ruff-formatted at init while template renders are
  raw Jinja output, so the byte-level 3-way merge misread formatting as user
  edits and conflicted wherever real template changes landed nearby. Python
  files are now compared and merged through ruff normalization, matching
  what the add/remove path already did, and the fallback path warns instead
  of degrading silently.
- **ruff is now a runtime dependency**: installs without dev extras (uvx,
  pip) previously had no ruff binary, so every Python merge silently fell
  back to the raw byte-level path. A test now guards the dependency.
- **`find-free-port.sh` false-busy on macOS**: Darwin allocates ephemeral
  source ports sequentially, so probing a port near a recent bind made
  connect() pick source == destination and fail with EINVAL, which read as
  busy for every candidate. The probe retries on EINVAL, keeping `make
  serve` port autodiscovery reliable in and near the ephemeral range.

## [0.9.0] - 2026-07-06

### Added

- **Neon Postgres provider**: new `postgres_provider` template question
  (`container` or `neon`). Local development keeps the Postgres container;
  production points at Neon, with pooler-safe connection arguments detected
  from the URL. No new dependencies. Guided and interactive init prompt for
  the provider on Postgres stacks.

### Fixed

- **`aegis update` backfills new template questions**: questions added by a
  newer template version (such as `postgres_provider`) are reconciled into
  the project's preserved answers file during update instead of being lost.
- **Stripe webhook forwarder no longer stalls on chatty output**: the
  dev-mode stripe-cli forwarder drains stdout in the background so a full
  pipe cannot block secret capture, with timeout handling around reads.

### Changed

- **Dependency pins hardened**: `typer` pinned to 0.26.8 (newer releases
  fail at class-body evaluation on Python 3.11/3.12); `copier` held below
  9.15 (9.15 relocates the answers file out of the generated project, which
  breaks `aegis update`), with a dependabot ignore rule so the ceiling is
  not silently widened.

## [0.8.1] - 2026-06-28

### Added

- **Traffic monitor ("who's hammering you")**: Overseer's Backend modal gains a
  **Traffic** tab showing top source IPs by request volume over a rolling
  window, flagging any single source that dominates traffic (read-time
  dominance check). A `TrafficMiddleware` tallies requests per client IP
  (proxy-aware via `get_client_ip`), backed by Redis when the component is
  present (shared across the webserver/scheduler/worker processes, survives a
  restart for the bucket TTL) and an in-memory store otherwise (per-process,
  resets on restart) — the same Redis-or-dict fallback `CacheService` uses, so
  the live panel works with or without Redis. Recording is fire-and-forget so
  it never adds latency to the request path. Admin-gated `GET
  /api/v1/traffic/sources` (open on auth-less stacks, matching `/health/`).
  Tunable via `TRAFFIC_MONITOR_ENABLED`, `TRAFFIC_WINDOW_HOURS`,
  `TRAFFIC_DOMINANCE_SHARE`, `TRAFFIC_DOMINANCE_FLOOR`.

### Changed

- **Rolling deploy no longer depends on `docker-rollout`**: `aegis deploy
  --rolling` now rolls the webserver in-process, starting a second replica
  and polling its container HEALTHCHECK status (`healthy`/`unhealthy`/
  `starting`) instead of shelling out to the `docker-rollout` plugin. The
  container's own HEALTHCHECK budget (`start_period + retries x interval`)
  is the single source of truth, so a slow-but-healthy boot is never rolled
  back by a wall clock, and no extra tooling needs to be installed on the
  deploy host. `--rollout-timeout` is now only a long runaway-guard ceiling.

### Fixed

- **`aegis update` records the correct template commit**: the commit stamped
  into the answers file after an update could be wrong, which skewed the
  starting point of the next update; it is now derived and verified
  explicitly.

## [0.8.0] - 2026-06-15

### Added

- **Guided `aegis init`**: a full-screen, interactive setup is now the default
  for `aegis init`, walking through components and services with a live review
  screen before generating. `--quick` keeps the classic one-line prompts, and
  tiny terminals fall back to quick mode automatically. `--no-interactive` is
  unchanged.
- **`tasks statistics` CLI command**: report overall scheduler statistics
  (total, active, and paused tasks) straight from the project CLI, mirroring the
  data behind the admin-gated `/scheduler/statistics` endpoint.
- **Authenticated load testing**: `api-load-test run` now authenticates by
  default so auth-gated routes work without manual login. `--as-admin` mints a
  bearer token for an `ADMIN_USER_EMAILS` address, `--as-user` for a regular
  account, and `--anon` opts out.
- **`HF_TOKEN` setting**: authenticates the RAG embedding-model download from the
  Hugging Face Hub, silencing the unauthenticated-request warning and raising
  rate limits. Optional; public models still download without it.

### Changed

- **CLI brand pass**: warnings are now amber (`#F5A623`, matching the frontend)
  instead of violet; status icons are monochrome text glyphs (`✓ ⚠ ✗ ℹ`) colored
  by state instead of emoji, so they align to the terminal grid and render
  consistently everywhere; the load-test report is themed (teal progress bar,
  dim labels).
- **Quiet RAG model load**: the embedding model now loads without progress bars
  or log noise in CLI output.

### Fixed

- **gpt-5 family and o-series models in AI chat**: these reject any non-default
  `temperature` and returned a 400; temperature is now omitted for them so the
  streaming chat works.
- **`llm` CLI commands now run**: `list`, `current`, `use`, and `info` were
  declared `async def`, which Typer never awaits, so they exited without doing
  anything; they now execute correctly.
- **Deprecation warning** in the AI chat streaming path (`result.usage()` is a
  property in pydantic-ai 1.x, no longer a method).

### Documentation

- **Installation guide clarity**: explain what `uvx` is and that it ships with
  uv, distinguish `uvx` (ephemeral run) from `uv tool install` (persistent
  install), and correct the uvx version note (latest on first run, cached
  thereafter; `uvx aegis-stack@latest` to refresh). The CLI language section now
  lists all 9 supported locales (`en`, `de`, `es`, `fr`, `ja`, `ko`, `ru`, `zh`,
  `zh_Hant`) in a table instead of only Simplified Chinese.

## [0.7.0] - 2026-06-08

### Added

- **Rolling deploys**: zero-downtime, code-only `aegis deploy --rolling`. The
  webserver rolls over while still serving traffic and the worker queue is
  paused so in-flight jobs drain cleanly before workers restart.
- **Free-port auto-discovery for `make serve`**: picks an open host port instead
  of failing with "address already in use" when the default is taken.
- **CI/CD scaffolding in generated projects**: a GitHub Actions deploy workflow
  generated out of the box.
- **Scheduler**: run a scheduled job on demand from the project CLI, plus
  scheduler fixes.
- **Payment service**: Stripe-backed payment capability, with end-to-end tests.
- **Performance middleware** in generated projects.

### Changed

- **`aegis update` is now idempotent**: after a clean update it advances the
  copier baseline (`_commit` / `_template_version`) so a re-run is a no-op and
  future updates don't re-apply changes that are already present.
- `aegis update --to-version` accepts both PEP 440 (`0.7.0`) and tag (`v0.7.0`)
  forms.
- Dependency: typer bumped to 0.26.7.

### Fixed

- Rolling deploy no longer rolls back a slow-but-healthy webserver: the
  docker-rollout wait is sized to the container's own healthcheck budget
  (`-t`), not a fixed 60s wall clock.
- `make serve` port detection no longer reports a busy port as free under load
  (a timed-out probe is treated as in-use, not free).

---

## [0.4.0] - 2025-12-07

### Added

#### TaskIQ Worker Backend
- Alternative worker backend using TaskIQ: `uvx aegis-stack init my-app --components "worker[taskiq]"`
- Full feature parity with arq backend
- TaskIQ-specific pool management, registry, and queue implementations
- Load testing support for TaskIQ workers
- Health monitoring integration for TaskIQ

### Fixed

- Windows compatibility: Removed Jinja2 conditional syntax from template filenames
  - Files with `{% if %}` in names caused OS Error 123 on Windows
  - Affected: `tasks.py` and `scheduler.py` in Cookiecutter templates

### Changed

- Release workflow now creates draft releases with auto-generated notes

---

## [0.3.4] - 2025-12-03

### Changed

- Docker build optimization: only build image for one service instead of all

---

## [0.3.3] - 2025-12-03

### Changed

- Version bump and dependency updates

---

## [0.3.2] - 2025-12-03

### Changed

- Version updates

---

## [0.3.1] - 2025-12-03

### Fixed

- Fixed `make serve` command by refactoring magic string handling

---

  ## [0.3.0] - 2025-12-01

### Major Features

#### Dashboard V2 - Complete UI Overhaul
- Light and dark theme support with system preference detection
- Component modal system - detailed info panels for each component:
  - Scheduler modal: Job stats, task history, next run times, cron expressions
  - Worker modal: Queue depth, job history, worker health, Redis connection
  - Redis modal: Memory usage, connection stats, key counts
  - Database modal: Table stats, connection pool info, query metrics
  - Backend modal: Route inspection, middleware detection, request stats
  - AI modal: Provider status, model info, conversation history
  - Auth modal: User count, session stats, JWT configuration
  - Frontend modal: Component tree, render stats, routing info
- Modern card-based architecture with improved visual hierarchy
- Enhanced health check visualization

#### New CLI Features
- `aegis update` rollback support - automatically restore on failed updates
- `--template-path` flag - use local template directories for development
- `--verbose` flag - control output verbosity across all commands
- Improved error messages with actionable suggestions for generation failures

#### Comms Service (New Service Layer)
- Communication service foundation for inter-component messaging
- Event-driven architecture support
- Service discovery patterns

### Added

- Copier integration testing for template validation
- CI/CD parallelization for faster builds
- Commit badges in generated project READMEs
- Scheduler environment variable configuration
- Enhanced Overseer documentation

### Fixed

- `aegis update` now correctly targets HEAD instead of latest tag
- Template path handling with `git+file://` URL format for Copier
- Dashboard rendering edge cases with component state

---

## [0.2.1] - 2025-11-10

### Fixed

- Minor bug fixes and stability improvements
- Added verbosity flag foundation

---

## [0.2.0] - 2025-11-05

### Major Features

  #### Dynamic Component Management
  - **NEW**: `aegis add` command - Add components to existing projects post-generation
  - **NEW**: `aegis remove` command - Remove components from existing projects
  - **NEW**: `aegis update` command - Update projects with latest template changes
  - **NEW**: Copier template engine support with version tracking
  - Projects can now evolve after creation (Copier-based projects only)
  - Intelligent dependency resolution (e.g., worker auto-adds Redis, auth auto-adds database)
  - File-level component management without full project regeneration
  - Automatic dependency installation and code formatting after changes

  #### Services Architecture (Business Logic Layer)
  - **NEW**: Authentication Service (`--services auth`)
    - JWT-based authentication with access and refresh tokens
    - User registration, login, and profile management
    - Password hashing with bcrypt
    - Protected API routes with FastAPI dependency injection
    - Database migrations via Alembic
    - User management CLI commands (`create-user`, `list-users`, `delete-user`, etc.)
    - Comprehensive test suite with 52+ authentication tests
    - Automatically includes database component

  - **NEW**: AI Service (`--services ai`)
    - PydanticAI integration for type-safe AI interactions
    - Multi-provider support (OpenAI, Anthropic, Gemini, Groq)
    - Streaming chat responses with markdown rendering
    - Conversation memory and persistence to database
    - Interactive CLI chat interface with rich formatting
    - Health monitoring for AI provider connectivity
    - Environment variable configuration
    - API endpoints for chat operations

  #### Enhanced Scheduler Component
  - **NEW**: SQLite-backed persistence option (`--scheduler-backend sqlite`)
  - Automatic database backup jobs when scheduler + database combined
  - Task monitoring API endpoints
  - Interactive CLI for viewing and managing scheduled tasks
  - Enhanced health checks with task execution tracking
  - Job statistics and history

### Added

  #### CLI Commands
  - `aegis add` - Add components to existing projects
  - `aegis remove` - Remove components from projects
  - `aegis update` - Update projects with latest templates
  - `aegis services` - List available services
  - `aegis components` - Show detailed component information
  - `aegis version` - Display CLI version
  - Template engine selection via `--engine` flag (copier or cookiecutter)
  - Interactive service selection during project creation
  - Component backend selection (e.g., `--scheduler-backend sqlite`)

  #### Developer Experience
  - **uvx support** - Run without installation (`uvx aegis-stack init my-project`)
  - Enhanced dashboard with component and service health cards:
    - Auth service card (user count, health status, database connection)
    - AI service card (provider status, model info, conversation stats)
    - Scheduler card (job stats, task history, next run times)
    - Worker card (queue stats, job history, worker health)
    - FastAPI card (route inspection, middleware detection)
    - Database card (table stats, connection pool info)
    - Redis card (memory usage, connection statistics)
  - Load testing CLI with visual progress indicators
  - FastAPI middleware and route inspection utilities
  - Rich terminal formatting for AI chat (markdown, code blocks, tables)
  - Comprehensive CLI tools for component management

  #### Testing & Quality
  - Migrated from mypy to `ty` for faster type checking
  - Extensive test coverage for auth service (52+ tests)
  - Extensive test coverage for AI service
  - Template parity tests (Cookiecutter vs Copier output validation)
  - Component addition/removal integration tests
  - Auth integration tests (registration, login, JWT flows, protected routes)
  - AI conversation persistence tests
  - Middleware and route inspection tests
  - Extended test matrix for component combinations
  - Clean validation workflow for template testing

  #### Documentation
  - Complete auth service documentation (API reference, CLI commands, integration guide, examples)
  - Complete AI service documentation (provider setup, API reference, CLI commands, integration)
  - Services architecture guide and dashboard integration docs
  - "Evolving Your Stack" guide - post-generation component management philosophy
  - Scheduler persistence and CLI documentation
  - Enhanced installation guide (uvx, uv tool, pip methods)
  - Integration patterns documentation
  - Component-specific CLAUDE.md files for AI development context
  - Release process documentation with PyPI/TestPyPI workflow

  #### Infrastructure
  - GitHub Actions workflow for automated PyPI releases
  - TestPyPI pre-flight testing workflow
  - PyPI Trusted Publishing (OIDC, no API tokens)
  - Template versioning and compatibility tracking
  - Copier template infrastructure with `.copier-answers.yml`
  - Post-generation task system refactored
  - Component file management utilities
  - Service dependency resolver
  - Manual updater for Cookiecutter-based projects

### Changed

  - **Default template engine** is now Copier (Cookiecutter still fully supported via `--engine cookiecutter`)
  - Type checker migrated from mypy to `ty` for improved performance
  - Enhanced dashboard UI with modern card-based architecture
  - Improved component dependency resolution logic
  - Better error messages with actionable suggestions
  - Scheduler component refactored with service layer separation
  - Worker health check registration improved
  - Database health checks enhanced with connection pool monitoring
  - Restructured CLI command organization into separate modules
  - Dashboard rendering optimizations

### Fixed

  - Dashboard rendering bugs with component state management
  - Worker type annotations and kwargs handling
  - arq worker info retrieval issues
  - Scheduler component integration edge cases
  - Database card rendering and refactoring issues
  - Redis component card state updates
  - FastAPI middleware detection for edge cases
  - Template generation with various component combinations
  - Health check caching race conditions

### Security

  - JWT-based authentication with secure token handling
  - Password hashing with bcrypt (cost factor 12)
  - Protected API routes with dependency injection patterns
  - Secure user model implementation
  - API key handling for AI providers
  - Environment variable-based secrets management

### Performance

  - Faster type checking with `ty` replacing mypy
  - Optimized component dependency resolution
  - Improved dashboard rendering performance
  - Enhanced health check caching strategies
  - Reduced template generation time

### Statistics

  - 62 pull requests merged since v0.1.0
  - 456 files changed (72,387 insertions, 4,590 deletions)
  - 8 new CLI commands
  - 2 new services (auth, AI)
  - 13+ new documentation files
  - 100+ new test files
  - 10 weeks of development (Aug 28 - Nov 5, 2025)

### Highlights for Users

  1. **Your stack can now evolve** - Add/remove components after project creation
  2. **Authentication ready** - Production JWT auth with one command (`--services auth`)
  3. **AI-ready** - Multi-provider AI integration built-in (`--services ai`)
  4. **No installation needed** - Run with `uvx aegis-stack init my-project`
  5. **Scheduler persistence** - SQLite-backed job storage for reliability
  6. **Enhanced DX** - Rich CLI tools, better dashboard, comprehensive health monitoring

### Notes

  - Copier is now the default template engine, enabling `aegis add/remove/update` commands
  - Both Copier and Cookiecutter templates are fully supported
  - Auth service automatically includes Alembic for database migrations
  - AI service supports OpenAI, Anthropic, Gemini, and Groq providers
  - Scheduler persistence requires database component
  - Template version compatibility tracked in `.copier-answers.yml` (Copier projects)
  - Worker component still requires explicit Redis component specification

  ## [0.1.0] - 2025-08-27

  ### Added
  - Initial release of Aegis Stack CLI tool
  - Database component with SQLite/SQLModel ORM integration
  - FastAPI backend with health monitoring system
  - Flet frontend for web and desktop applications
  - Worker component with arq/Redis for background tasks
  - Scheduler component with APScheduler
  - Docker containerization support
  - Comprehensive testing infrastructure with pytest
  - Type checking with mypy and pydantic plugin
  - Auto-formatting with ruff
  - Project generation via `aegis init` command
  - Component dependency resolution system
  - Database health checks with detailed metrics
  - Transaction rollback testing fixtures
  - Template validation system

  ### Fixed
  - Database test isolation issues
  - Type checking for Pydantic models with mypy plugin
  - Template linting issues in generated projects

  ### Components
  - Backend (FastAPI) - Always included
  - Frontend (Flet) - Always included
  - Database (SQLite/SQLModel) - Optional
  - Worker (arq/Redis) - Optional
  - Scheduler (APScheduler) - Optional

[0.4.0]: https://github.com/lbedner/aegis-stack/compare/v0.3.4...v0.4.0
[0.3.4]: https://github.com/lbedner/aegis-stack/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/lbedner/aegis-stack/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/lbedner/aegis-stack/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/lbedner/aegis-stack/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/lbedner/aegis-stack/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/lbedner/aegis-stack/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/lbedner/aegis-stack/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lbedner/aegis-stack/releases/tag/v0.1.0