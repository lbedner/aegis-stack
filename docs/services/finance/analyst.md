# Finance Analyst

The finance analyst produces one report a day about your money, and the
report is formulaic on purpose: the same sections in the same order every
day - a headline on what needs attention, then cash and bills, credit,
spending, and investments - so you learn where to look. The layout and
every figure in it are computed by code (`build_report_facts` +
`render_report`); the local model reads a snapshot of your accounts and
returns ONLY the commentary sentences that ride under each section
(structured `SectionCommentary` output). A wrong number in the report is
therefore always a facts bug with one place to fix, never a model
hallucination to argue with. Sections without figures are omitted by code;
the model cannot conjure or drop one.

It runs on a model you host yourself. No account data leaves the machine.

## The idea: rules detect, the agent narrates

Anomaly detection is deterministic. Rule code in
`app/services/finance/categorize/insights.py` decides what is unusual and
writes `finance_insight` rows. The agent never makes that call.

| Rule | Fires when |
| --- | --- |
| `price_hike` | A fixed recurring charge costs more than its own average |
| `fee_charged` | A bank or finance fee lands on an account |
| `overspend_category` | A category is above 1.5x its own three-month median |
| `large_transaction` | One charge is far outside its own account's recent norm |
| `missed_recurring` | A bill or paycheck did not arrive after its grace window |
| `card_overdue` | The institution reports a credit account past due |
| `min_payment_gap` | A minimum payment due within 14 days exceeds cash on hand |
| `high_apr_carry` | A balance is provably accruing interest at 20% APR or more |
| `credit_utilization` | A card is at 80% of its limit (critical at 95%) |
| `cash_runway` | Scheduled bills walk the cash balance below zero within 60 days |
| `subscription_creep` | The subscription total is 1.25x its three-month median |

The credit rules read the provider's own liability detail (statement balance,
minimum payment, due date, APRs), so "your card is in trouble" is something the
system is told to look for, never something a model happens to notice.

The agent's only job is to explain those findings, plus the surrounding
numbers, in a paragraph a person will actually read. This split is what makes a
small local model safe to point at real money: a bad answer is a badly worded
paragraph, never an invented alert.

The agent is also forbidden to do arithmetic - and since the report's figures
are rendered by code from `ReportFacts`, the model's words cannot change a
number even when it misbehaves. Its commentary is stored alongside the
rendered body in the note's metadata for inspection.

## What the agent sees

Each turn, a memory module called `finance_snapshot` renders the current state
as labeled plain text:

- Every account with its type, classification, and balance
- Net worth today, and the change over 30 and 90 days
- Credit cards and loans with limit, utilization, APR, minimum payment, and
  due date - the same fields the credit rules read, through the same helpers
- Current investment positions, largest first, pre-valued
- Income against spend for the last six months, with the net pre-signed
- This month's spending per category next to that category's own recent norm
- The last ten transactions, newest first - enough to anchor "that large
  charge" to a name and a date, not a register dump
- Open findings from the rules above, most severe first
- The cash projection: today's cash walked through scheduled bills and income,
  with the lowest point and any below-zero crossing pre-computed
- Recurring payments expected in the next 14 days

It sees nothing else. Account numbers never appear in the snapshot, and every
list is capped so a deep history cannot flood the model's context window.

## Setting it up

The analyst ships with any project generated with both the finance and AI
services, on a database-backed AI backend.

1. Point the AI service at your local model. In `.env`:

   ```
   AI_PROVIDER=ollama
   AI_MODEL=gpt-oss:20b
   OLLAMA_BASE_URL=http://host.docker.internal:11434
   ```

   `AI_MODEL` is the full Ollama tag, including the size suffix. Any pulled
   model works; larger ones write better notes and take longer.

   `AI_MODEL` is only the starting point. If a model has been selected with
   `llm use` or from the dashboard, that choice is stored in the database and
   applied over these values when each process starts, so it is what actually
   answers. `llm current` shows which model is live.

2. Make the local catalog visible to the dashboard:

   ```
   uv run <project> llm sync --source=ollama
   ```

3. Confirm the agent is registered:

   ```
   uv run <project> agents list
   ```

   You should see `finance-analyst` with one memory module. If the list is
   empty, the registry was never seeded, which happens when the AI service was
   added to an existing project rather than chosen at generation. Seed it in
   place:

   ```
   uv run python -c "from app.core.db import SessionLocal; \
   from app.services.ai.fixtures import load_all_ai_fixtures; \
   load_all_ai_fixtures(SessionLocal())"
   ```

## When it runs

The scheduler writes one note per owner per night, at 02:30. That is half an
hour behind the rules pass at 02:00, so the note is written from the current
night's findings rather than the previous night's.

Notes are deduplicated by date. A second run on the same day returns the
existing note without contacting the model, which matters because a local model
costs real seconds.

To write one now, use the Run analysis button on the Notes tab of the finance
dashboard, or call the endpoint directly:

```
POST /api/v1/finance/analyst/run           # returns today's note, no model call
POST /api/v1/finance/analyst/run?force=true  # discards it and writes a new one
```

The forced request waits on the model. Expect roughly 10 to 20 seconds for a
20B model on consumer hardware. That wait is the price of the data staying put.

## Where the notes appear

Notes are `finance_insight` rows with `insight_type` of `analyst_note`, so they
live in the same table as the findings but stay out of their surfaces. The
insight badge counts findings only, and the Insights list excludes notes. Ask
for them explicitly:

```
GET /api/v1/finance/insights?insight_type=analyst_note
GET /api/v1/finance/insights?exclude_type=analyst_note
```

## Tuning it

Both the agent and its memory module are ordinary registry rows, editable from
the AI dashboard or directly:

- `system_prompt` controls the voice and the rules the note follows.
- `temperature` defaults to 0.2. The task is faithful restatement, not
  invention.
- `max_tokens` defaults to 2000. That is generous on purpose: a reasoning model
  spends output tokens thinking before it writes the sentences you see.
- `model_id` pins this one agent to a specific model, which is how you give the
  analyst a different model from the one the chat assistant uses. Leave it
  empty and the agent follows whatever the AI service is running. Note that it
  selects a model, not a provider, so the pinned name has to be available from
  the configured provider.

A re-seed never overwrites an edited row, so tuning survives.

If a note reads badly or drifts from the numbers, change the prompt or the
snapshot. Do not post-process the output: the moment something rewrites what
the model said, the guarantee that every figure came from the snapshot is gone.

## When it does not write

The analyst skips quietly, logs why, and leaves no row when:

- The owner has no accounts, so there is nothing to narrate.
- The agent row is missing or inactive.
- The model is unreachable, still pulling, or out of memory.

A stopped Ollama is an ordinary night. It costs a log line, never a note
containing an error message, and never the rest of the nightly job.
