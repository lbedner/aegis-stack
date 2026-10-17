# Finance Service — aegis-stack Implementation Plan

> A personal-finance aggregator (Quicken / Empower / Monarch class) authored as a **first-class
> aegis-stack template service**, gated by `include_finance` and installable via `aegis add-service
> finance` — so any project generated from the stack can opt in. Aggregates bank / credit-card /
> brokerage accounts, imports Quicken/OFX/CSV, charts net worth over time, surfaces "wasting money"
> insights, and (when `include_ai`) feeds those insights to the Illiana AI layer.
>
> **Status: planning only — nothing built.** This document is the blueprint. The load-bearing artifact
> is the schema: [`finance-schema-canonical.md`](./finance-schema-canonical.md) (33 tables).
>
> **Target repo:** `aegis-stack` (the template), NOT a one-off in a generated project. Everything lives
> under `aegis/templates/copier-aegis-project/{{ '{{ project_slug }}' }}/…` as `.jinja`/static sources,
> plus registry entries in `aegis/core/`.

---

## 0. TL;DR

- **Packaging:** a new gated service `include_finance`, wired the way `payment`/`insights` are — in **two parallel systems** that must stay in sync: (1) the **Copier template** (`{% if include_finance %}` blocks across ~17 `.jinja` files) and (2) the **Python registry** `aegis/core/services.py` `SERVICES["finance"]` (the single source of truth for pruning, `aegis add-service`, migrations, `aegis update` detection, and `aegis init` listing).
- **Migrations are declarative, not hand-written.** The 33 tables become a `FINANCE_MIGRATION` `ServiceMigrationSpec` (list of `TableSpec`) in `aegis/core/migration_generator.py`. Revision IDs are **auto-assigned** so the chain is valid for any `include_*` combination — there is no "031".
- **Dual-engine (sqlite + postgres).** Partial-unique indexes, CHECK constraints, and `on_conflict` UPSERT all work on both; finance tables get a Postgres `finance` schema. The dedup contract is unchanged from the design.
- **Connectivity (unchanged from the design):** Plaid-first (Chase/AMEX/Vanguard), **SnapTrade for Fidelity** (Plaid-via-Fidelity is unreliable), manual/file import as a permanent fallback — behind one provider-polymorphic connection layer, so adding a provider later needs zero new tables.
- **Prereqs:** finance declares `required_components=[BACKEND, DATABASE, SCHEDULER]`, `recommended_components=[WORKER]`; auth is **integrated-when-present** via the `finance_auth_link` migration (which adds the `owner_user_id -> user` FK only when auth is included), so `required_services=[]` and finance runs standalone too. The resolver/validator enforce the component prereqs at `init` and `add-service`.
- **UI = Flet dashboard card + modal** (the template's convention — `payment_card.py`/`insights_card.py`). The Alpine "Overseer tabs" from the earlier Pulse draft are a *downstream* concern; the template ships Flet.
- **Illiana hook is real here** (unlike Pulse): the template's AI service exists, so a conditional `finance_context.py` (gated `{% if include_ai and include_finance %}`) plugs finance data in as a memory module or a tool (live data stays out of the system prompt, ON-18). v1 "wasting money" signals ship rule-based (no AI required).
- **Encryption exists in the template** (`app/core/encryption.py`, AES-256-GCM). The **key-rotation CLI does not** (it's Pulse-only — pending auth/encryption backport). So the "register encrypted columns in the rotation CLI" step is deferred/blocked on that backport (noted in §11).

---

## 1. What & scope

Same product as the design brief. In scope (v1, populated when `include_finance` is selected):
1. **Plaid** connect for Chase (checking/savings/credit + liabilities) and AMEX (cards).
2. **SnapTrade** connect for Fidelity + brokerages (holdings/positions/trades) — Plaid attempt + manual fallback.
3. **Import** existing Quicken (QIF, QFX/OFX) + bank CSV, deterministic dedup.
4. **Accounts + Transactions** on the Flet dashboard.
5. **Net worth over time** (materialized daily snapshots) + **investments/holdings**.
6. **Manual accounts & valuations** (real estate, vehicles, crypto — anything with no API).
7. **Rule-based "wasting money" insights** (recurring/subscription, price hikes, fees, overspend), emitted through the existing `insight_event` machinery when `include_insights`, else as finance-local rows.

Non-goals / later (tables exist, unpopulated): tax-grade cost basis / lots, trade execution, budgeting UI, crypto exchange-key + on-chain connections, rules-engine UI, attachments, the Illiana narration wiring. See the design docs.

The 33-table schema, connectivity decisions, import/dedup, net-worth engine, and insight signals are documented in **[`finance-schema-canonical.md`](./finance-schema-canonical.md)** and the [`finance-research/`](./finance-research/) briefs and are **unchanged** by the aegis-stack retargeting. This plan focuses on the parts that DO change: packaging.

---

## 2. Packaging as an aegis-stack service (the centerpiece)

Wiring a gated service happens in **two parallel systems**. Mirror `payment` (the closest DB + API + frontend + migration analog) throughout.

### 2.1 The Python registry — `aegis/core/services.py` `SERVICES["finance"]`
This `ServiceSpec` is the single source of truth. Copy the `payment` spec and fill:
- `name="finance"`, `description`, `long_description`, `docs_path`, `version`, `verified=True`, `aegis_version`.
- `type` — reuse a `ServiceType` or add a member (+ `SERVICE_TYPE_I18N_KEYS` entry).
- **Dependencies:** `required_components=[BACKEND, DATABASE, SCHEDULER]`, `recommended_components=[WORKER]`, `required_services=[]` (auth is integrated-when-present via `finance_auth_link`, so finance runs standalone), `conflicts=[]`.
- **`pyproject_deps=[...]`** — the finance deps (see §2.4). A parity test (`test_pyproject_deps_parity`) checks this equals the `pyproject.toml.jinja` block, so keep them identical and in the same order.
- **`files=FileManifest(primary=[...])`** — every path finance owns (service dir, api dir, cli file, Flet card+modal, tests, seed). This drives post-gen **pruning** when `include_finance=false`. Use `extras={"finance_<opt>": [...]}` for option-gated sub-files.
- **`template_files=[...]`** — dirs rendered by `ManualUpdater` on `aegis add-service` (post-generation installs).
- **`marker_path="app/services/finance"`** — drives `aegis update` disk detection.
- **`migrations=[FINANCE_MIGRATION]`** (+ any cross-service link spec).
- **`wiring=PluginWiring(routers=[...], deps_providers=[...], dashboard_cards=[...], dashboard_modals=[...])`**.
- **`options=[OptionSpec(...)]`** if finance exposes `finance[...]` bracket options (e.g. `finance[snaptrade]`); register the handler in `aegis/cli/callbacks.py::SERVICE_OPTION_HANDLERS`.

Once this spec exists, `aegis init` listing, `aegis add-service finance`, pruning, and update-detection all light up automatically.

### 2.2 The migration — declarative `FINANCE_MIGRATION` in `aegis/core/migration_generator.py`
- Author the 33 tables as `TableSpec`/`ColumnSpec`/`IndexSpec`/`ForeignKeySpec`/`CheckConstraintSpec` (the DSL supports everything the schema needs — partial-unique `where=`, `ondelete=`, cross-schema `ref_schema="auth"`, check constraints). The `finance_transaction ↔ finance_transfer` circular FK is an `AlterTableSpec` applied after both tables exist.
- Set `schema="finance"` on the `ServiceMigrationSpec` (Postgres schema; ignored on SQLite).
- Add a **finance block to `get_services_needing_migrations(context)`** (mirror payment's; append `"payment_auth_link"`-style cross-service link only if needed — finance's `owner_user_id → auth.user` is handled via `ref_schema`, not a separate link migration, unless auth is toggled independently, in which case follow the `payment_auth_link` conditional pattern).
- In `aegis/core/copier_manager.py`: derive `is_finance_included`, add to `needs_migration_files`, and add `AnswerKeys.FINANCE: is_finance_included` to the migration `context`.
- Revision numbering is automatic (`get_next_revision_id` / `get_previous_revision`) — **do not hardcode**.

### 2.3 `copier.yml`
```yaml
include_finance:
  type: bool
  help: "Include finance aggregator service (Plaid/SnapTrade/import)?"
  default: false

finance_plaid:      { type: bool, default: true,  when: "{{ include_finance }}" }
finance_snaptrade:  { type: bool, default: true,  when: "{{ include_finance }}" }
finance_investments:{ type: bool, default: true,  when: "{{ include_finance }}" }
finance_import:     { type: bool, default: true,  when: "{{ include_finance }}" }
```
- Append `or include_finance` to `_include_migrations` (copier.yml ~:327) **and** to the alembic gate in `pyproject.toml.jinja` (~:78).
- Add `include_finance:` (+ sub-flags) to `.copier-answers.yml.jinja`.
- Note: the `_X_deps` computed vars are **dead** (referenced only in copier.yml); real deps go in §2.4.

### 2.4 Dependencies (two places, kept in parity)
- `pyproject.toml.jinja` (~:118): a `{%- if include_finance %}` block listing deps.
- `SERVICES["finance"].pyproject_deps=[...]` — identical list/order.
- Candidate deps: `plaid-python>=…` (Plaid), a SnapTrade SDK or `httpx` (SnapTrade), `ofxtools>=…` (OFX/QFX), `quiffen>=…` (QIF). Keep provider deps gated by their sub-flags where possible.

### 2.5 The `{% if include_finance %}` template touch-list (mirror `include_payment`, ~17 files)
`app/components/backend/api/routing.py.jinja` (router import + mount) · `api/deps.py.jinja` (finance deps provider) · `app/core/config.py.jinja` (PLAID_*/SNAPTRADE_* settings block) · `app/components/frontend/dashboard/cards/__init__.py.jinja` (import + grid + the OR-guards that render the services row) · `.../modals/__init__.py.jinja` · `app/cli/main.py.jinja` (try/except `add_typer` for `finance.py`) · `alembic/env.py.jinja` (model import block) · `app/components/backend/startup/database_init.py.jinja` (`finance_needs_migrations` + seed hook) · `app/components/backend/startup/component_health.py.jinja` · `app/components/scheduler/main.py.jinja` (if finance schedules jobs — §7) · `pyproject.toml.jinja` · `.copier-answers.yml.jinja` · `Dockerfile.jinja` · `tests/conftest.py.jinja` · `docker-compose*.jinja` (only if finance needs a new service/env). Plus `post_gen_tasks.py` alembic-removal gets a `finance_needs_migrations` term.

### 2.6 New service tree (rendered under `{{ '{{ project_slug }}' }}/`)
```
app/services/finance/                       # models.py(.jinja), schemas, finance_service.py, deps.py,
  providers/{base,plaid,snaptrade,manual}.py(.jinja)   # constants, health, seed, sub-services,
  importers/{base,ofx,qif,csv_profiles}.py            # categorize/, recurring.py, jobs.py.jinja
  finance_context.py.jinja                  # {% if include_ai %} Illiana provider (§9)
app/components/backend/api/finance/         # router.py.jinja, views/display endpoints
app/components/frontend/dashboard/cards/finance_card.py      # Flet card (§10)
app/components/frontend/dashboard/modals/finance_modal.py    # Flet modal (§10)
app/cli/finance.py.jinja                    # import-quicken / import-csv / sync / connect (Typer)
tests/services/test_finance_*.py
docs/services/finance/                      # shipped service docs
```

### 2.7 Prerequisites & validation
Declared on the spec (§2.1) and enforced by `validate_service_dependencies()` + `service_resolver.py`. Finance requires database + scheduler (components) and auth (service, for `owner_user_id`). If a sub-option needs more (e.g. a future `finance[per_user]`), use the conditional cross-service block in `service_resolver.py` (the `insights[per_user] → auth[org]` precedent). Missing components are surfaced + auto-added at `add-service` time.

---

## 3. Connectivity — the decision (unchanged)

Provider-polymorphic connection layer. Same table as the design: **Plaid** (Chase/AMEX/Vanguard, free Trial = 10 live Items incl. Investments), **SnapTrade** for **Fidelity**/brokerages ($1/user/mo, self-serve, rides Akoya — because **Fidelity-via-Plaid is unreliable**, Fidelity states it "does not utilize Plaid"), **manual/file import** as the permanent fallback, and crypto later (exchange key / on-chain / manual — Plaid doesn't cover it). In the template these are gated by `finance_plaid` / `finance_snaptrade` sub-flags; the `manual` provider always ships. Details + the Fidelity caveat: [`finance-research/03-stocks-crypto-connectivity-brief.md`](./finance-research/03-stocks-crypto-connectivity-brief.md).

---

## 4. Data model

The full 33-table schema, dedup contract, modeling decisions, ER diagram, and existing-schema touchpoints are in **[`finance-schema-canonical.md`](./finance-schema-canonical.md)**. For aegis-stack it is realized as (a) `app/services/finance/models.py` SQLModel classes and (b) the declarative `FINANCE_MIGRATION` spec (§2.2) — both dialect-aware, in a Postgres `finance` schema. 26 tables populate in v1; 7 ship reserved-but-empty (the "never add a table later" insurance). Money = int minor units; enums = String+CheckConstraint (owned) / TEXT (provider taxonomies); two-lane dedup via partial-unique indexes with a `ck_dedup_lane` guard.

---

## 5. Provider integration (Plaid & SnapTrade adapters)

`app/services/finance/providers/` — a `BaseFinanceProvider` protocol with normalized result dataclasses, exactly like `payment/providers/` wraps Stripe behind `BasePaymentProvider`. `plaid.py` (official `plaid-python` SDK: Link token → public_token → `/item/public_token/exchange` → encrypted access_token; `/transactions/sync` cursor loop; `/investments/*`; `/liabilities/get`; webhook verify). `snaptrade.py` (brokerage authorization → aggregator_token; positions/balances/transactions normalized into the SAME `finance_account`/`finance_security`/`finance_holding`/`finance_trade` tables). `manual.py` (no-op). Token exchange mirrors the existing OAuth "connect-for-data" precedent; secrets encrypted via `app.core.encryption.encrypt_secret(..., context="finance_connection:{id}:{col}")`. Provider files are gated by their `finance_plaid`/`finance_snaptrade` sub-flags; the base protocol + manual always ship. Full flow (Link, sync invariant, pending→posted, webhooks, re-auth): [`finance-research/01-domain-brief.md`](./finance-research/01-domain-brief.md).

---

## 6. Import pipeline — Quicken / OFX / CSV / manual

Mirrors the blog `/import` `UploadFile` pattern. `POST /api/v1/finance/import` dispatches by extension (`.qfx`/`.ofx` → `ofxtools`; `.qif` → `quiffen`; `.csv` → data-driven `finance_import_profile`). Typer CLI `finance import-quicken`/`import-csv` runs the same ingest synchronously. Two-lane dedup + cross-source reconciliation exactly per the schema doc's §2. `finance_import_batch`/`_row` give reversible, review-before-commit imports.

---

## 7. Sync & scheduled jobs (backend-agnostic — inline, NOT taskiq)

**Key difference from the Pulse draft:** in the template, `worker_backend` ∈ {arq, taskiq, dramatiq}, and payment/insights do NOT ship a worker queue — they run scheduled work **inline as async functions in the scheduler** (`app/services/insights/jobs.py.jinja` → `async def collect_*_job()`, wired in `scheduler/main.py.jinja` behind `{% if include_insights %}`). Finance follows this: `app/services/finance/jobs.py.jinja` with `async def finance_sync_job()` / `finance_recompute_balances_job()`, registered via `scheduler.add_job(...)` inside a `{% if include_finance %}` block. This is backend-agnostic (APScheduler just awaits the coroutine). Only if finance genuinely needs distributed execution do we add a `queues/finance{,_taskiq,_dramatiq}.py` triplet (post-gen renames per backend) — deferred; bound payloads/date ranges regardless (worker-OOM history).

---

## 8. Net-worth engine

Unchanged: materialized daily `finance_balance_snapshot` (per account) + `finance_net_worth_snapshot` (per user), recomputed by the inline scheduler job from transactions + valuations + holdings×prices. Net worth is a persistence problem, not derivable from partial history — snapshots start day one. Manual/illiquid assets ride the same series via `finance_valuation` (source-tagged + staleness).

---

## 9. Categorization & "wasting money" insights (+ the real Illiana hook)

- **Categorization:** capture Plaid PFC raw + map to an owned category tree; data-driven `finance_rule` engine for overrides; `finance_category_alias` for free-text QIF/CSV categories.
- **Insights (rule-based, ship without AI):** recurring/subscription detection (`finance_recurring_stream`), price-hike, fee/interest, category overspend vs baseline. When `include_insights`, emit through the existing `insight_event` machinery (the country-spike rule pattern) so it renders in the insights UI; otherwise store finance-local `finance_insight` rows.
- **Illiana (works in the template):** unlike Pulse, the template's AI service is real when `include_ai`. Ship `app/services/finance/finance_context.py.jinja` gated `{% if include_ai and include_finance %}`, as a memory module or a tool (live data stays out of the system prompt, ON-18), it assembles accounts/spend/streams so Illiana can narrate "you're wasting money on X." No cross-repo port needed; it's a conditional file.

---

## 10. UI — Flet dashboard card + modal (the template convention)

The template's dashboard is **Flet** (no web_frontend/Alpine — that's Pulse-only). Finance ships `frontend/dashboard/cards/finance_card.py` (net-worth headline + connection-health chips) and `modals/finance_modal.py` (Accounts, Transactions, Net Worth, Investments views), registered via `PluginWiring.dashboard_cards/dashboard_modals` and the `cards/__init__.py.jinja` grid + OR-guards — mirroring `payment_card.py`/`insights_card.py`. (A downstream project with its own web_frontend, like Pulse, would additionally render finance in its own idiom; that is out of scope for the template.)

---

## 11. Security & encryption

- **Encryption primitive exists in the template:** `app/core/encryption.py` (AES-256-GCM, `encrypt_secret/decrypt_secret` with row-bound AAD `context`). Finance stores provider tokens as ciphertext columns on `finance_connection`, encrypted in the service layer; `__repr__` masks them. Precedent: insights `Project.plausible_api_key`.
- **Key-rotation CLI gap:** the template has **no `app/cli/security.py`** (Pulse-only; pending the auth/encryption backport). So the "register finance encrypted columns in the rotation CLI" step is **blocked/deferred** until that backport lands — flag it, and define the `_ENCRYPTED_COLUMNS` tuple in the finance service now so wiring it is a one-liner later. (Missing rotation coverage silently strands finance creds on a future key rotation — document loudly.)
- Read-only scopes only; never store bank credentials; Plaid webhook signature verified; `/item/remove` + soft-delete on disconnect to stop per-Item billing.

---

## 12. Config & env

- `app/core/config.py.jinja`: a `{% if include_finance %}` settings block — `PLAID_CLIENT_ID/SECRET/ENV/WEBHOOK_URL/REDIRECT_URI` (gated by `finance_plaid`), `SNAPTRADE_CLIENT_ID/CONSUMER_KEY` (gated by `finance_snaptrade`), `FINANCE_DEFAULT_CURRENCY`. Add a prod-safety `@model_validator` (require keys when `PLAID_ENV=production`), matching existing validators.
- `.env.example.jinja`: matching `{% if include_finance %}` documented block.

---

## 13. Testing

- **Template-generation tests** (the aegis-stack layer): `include_finance` on/off renders/prunes correctly; `test_pyproject_deps_parity` (spec vs jinja block); migration generation produces a valid revision chain across `include_*` combinations; `aegis add-service finance` on a generated project.
- **Service tests** (rendered project): importers (OFX/QIF/CSV) with known-debit/known-credit sign fixtures + re-import idempotency; dedup two-lane + cross-source reconciliation; transfer pairing; recurring detection; Plaid/SnapTrade adapters against sandbox.
- **Dual-engine:** run against **both** sqlite and postgres — the template supports both, and the pytest default may be sqlite (FK/partial-unique/`on_conflict` dialect paths verify on postgres). Follow existing services' conftest patterns.

---

## 14. Build phases

- **Phase 0 — Registry + schema + gating.** `SERVICES["finance"]` spec, `FINANCE_MIGRATION` (33 `TableSpec`), copier.yml flags, `pyproject`/`env.py`/`config`/`post_gen` gating, seeds (currencies + PFC category tree + institutions + import profiles). *Exit: `aegis init --include-finance` on sqlite AND postgres generates a project whose migration applies clean; `include_finance=false` prunes cleanly; parity test green.*
- **Phase 1 — Manual + import.** Manual accounts + valuations; OFX/QIF/CSV importers + `/import` + CLI; dedup; Flet card + modal (Accounts/Transactions). *Exit: import a Quicken/AMEX file, idempotent re-import.*
- **Phase 2 — Plaid.** `providers/plaid.py`, Link, `/transactions/sync`, webhook + health, inline sync job. Chase + AMEX. *Exit: sandbox item syncs; reconnect UX.*
- **Phase 3 — Investments + net worth.** Plaid Investments + **SnapTrade (Fidelity)**; securities/holdings/trades; snapshot engine; Investments + Net Worth views. *Exit: Fidelity holdings + net-worth chart.*
- **Phase 4 — Insights.** Transfer detection, recurring/subscription, rule-based "wasting money" via `insight_event`. *Exit: subscriptions + a price-hike/overspend insight.*
- **Phase 5 — Illiana + `aegis add-service`.** `finance_context.py` (when `include_ai`); finalize `template_files` + `ManualUpdater` path so `aegis add-service finance` works on existing projects. *Exit: add-service onto a generated app; Illiana narrates finance insights.*

---

## 15. Open decisions to confirm

Design defaults (money int minor units, disconnect retention, USD-only FX, high-confidence-only cross-source merge, SnapTrade-primary for Fidelity, Transactions+Investments+Liabilities at launch, self-contained trades) are in the schema doc. aegis-stack-specific ones:
1. **Sub-flag granularity** — one `include_finance`, or split `finance_plaid`/`finance_snaptrade`/`finance_investments`/`finance_import` as gating sub-questions? *(Default: sub-flags, providers gated individually.)*
2. **Worker: inline vs queue** — inline scheduler jobs (backend-agnostic, matches insights) vs a per-backend `queues/finance*` triplet for distributed sync. *(Default: inline for v1.)*
3. **Postgres-only vs dual-engine** — require postgres for finance, or fully support sqlite dev? *(Default: dual-engine, postgres recommended.)*
4. **Encryption/rotation dependency** — proceed with `encrypt_secret` now and defer rotation-CLI registration until the auth/encryption backport, or pull that backport forward first? *(Default: proceed; leave a `_ENCRYPTED_COLUMNS` hook.)*
5. **Insights coupling** — `insight_event` reuse requires `include_insights`; if absent, use finance-local `finance_insight`. Make finance *recommend* insights? *(Default: recommend, degrade gracefully.)*

---

## Appendix — research sources

- [`finance-schema-canonical.md`](./finance-schema-canonical.md) — the 33-table schema (now framed for the aegis-stack migration DSL).
- [`finance-research/00-codebase-conventions.md`](./finance-research/00-codebase-conventions.md) — conventions (captured from Pulse; the template shares them).
- [`finance-research/01-domain-brief.md`](./finance-research/01-domain-brief.md) — Plaid API, Chase/AMEX, Quicken/OFX/CSV formats, OSS schemas.
- [`finance-research/02-product-insights-brief.md`](./finance-research/02-product-insights-brief.md) — product teardowns + the hard problems.
- [`finance-research/03-stocks-crypto-connectivity-brief.md`](./finance-research/03-stocks-crypto-connectivity-brief.md) — Plaid Investments, Fidelity/SnapTrade/Akoya, crypto + manual.

> Note: the earlier Pulse-targeted plan (`aegis-pulse/docs/plans/finance-service-plan.md`) is superseded by this document. Its architecture/integration sections are largely reusable; the differences are exactly §2 (packaging), §7 (inline jobs), §10 (Flet UI), and §11 (rotation-CLI gap) here.
