# Evals

An eval asks the assistant something and checks what it did. A case is a message and the assertions you wish you'd had when you found a regression by reading logs. A case scores the **tools** the turn called first, and the prose second.

```bash
aegis init my-app --services "ai[sqlite,evals]"
```

To add it to an existing project, name the backend it already has, so the brackets don't ask for a different one: `aegis add-service "ai[sqlite,evals]"`.

Evals need Pydantic AI and a database: a dataset and its runs are rows, so `ai[evals]` on the memory backend is refused. On LangChain the option ships nothing, because LangChain's turns record no tool calls to score.

## A dataset

A dataset is Pydantic Evals' YAML, kept in the database as written (comments too), one row per dataset in `eval_dataset`. Every process of the app reads the same rows, and a deploy keeps them. The datasets the app ships are `evals/*.yaml` in the source tree; at startup, and before any `ai evals` command that reads datasets, each one whose name the database has never had is added, and one still as it was seeded is brought up to its file when the file changes (one that cannot be read is skipped with a warning). One edited, deleted or imported in the app stays as it is. A new project ships `evals/starter.yaml`:

```yaml
cases:
  - name: what is installed is read, not guessed
    inputs:
      message: which plugins does this app have?
      script:
        - tool: run_code
          args:
            code: "found = await plugins()\nfound"
        - text: Here are the plugins this app has installed.
    evaluators:
      - ToolCalls:
          tool: plugins
          times: 1
```

Each case runs as one real turn, through `AIService.chat()`, with the same agent, tools, context and persona that chat uses. The case is scored on the reply and on the `tool_trace` the reply keeps, which is the same trail Overseer shows under a message. A script's sandbox dispatches count as calls, so `plugins` above passes when it's called inside `run_code`.

`inputs.agent` asks a named agent instead of the default. `metadata.why` says why the case is there, and the Overseer shows it under the case's name, read from the dataset as it is now:

```yaml
  - name: what broke is read from the errors
    metadata:
      why: an answer about today's errors must come from the error log
    inputs:
      message: what went wrong today?
```

`evals/system.yaml` ships beside it: whether the assistant can talk about the app itself. It asks what the app is made of, how it is doing, what broke today, which tables it has, how a route is handled, the slowest request, what the AI cost, and something it cannot see (the CPU temperature), and each case passes on the read it makes before what it says.

### Writing one with the model

```bash
uv run my-app ai evals generate ops --about "Whether it reads how the app is doing before it answers" --like system --cases 5
```

The model in force writes dataset `ops` (Pydantic Evals' `generate_dataset`). It is told the default assistant's prompt and the app's map (its parts, tables and aggregates), so the cases are about this app, and each tool that assistant may call, with its arguments, so a check names a call it can make. It is also told every message a dataset already asks, so a new dataset repeats none, and `--like` hands it a dataset to write like (without its scripts). `--about` has to say something (10 characters or more): it is most of what steers the cases. `--about` becomes the dataset's leading comment, and each case gets a `why`.

Then each case runs once on that model, and only the cases that pass are kept, each with the script its turn took. The scripts are then played back the way `make evals-ci` plays them, and a case that fails there is dropped too, so nothing written fails in CI. A dropped case is named with the check that failed. Checks that read the run's spans (`ToolCorrectness`, `TrajectoryMatch`, `ArgumentCorrectness`, `MaxToolCalls`, `MaxModelRequests`, `HasMatchingSpan`) are left out, since CI keeps no spans; `ToolCalls` and `ToolOrder` check the same calls from the trace. Both runs are kept, as `generate` and `ci`. A name already taken is refused, and so is one taken while the cases run. The dataset is kept once, at the end, so a run never sees a half-made dataset, and when no case holds, nothing is kept. `--cases` is 1 to 20: each is a real turn on the model.

Overseer > AI > Evals > Datasets does the same from "New dataset", as a job (on the worker where there is one) that the tab follows.

### In and out

YAML is how a dataset comes in and goes out. `ai evals import` keeps each file as a dataset named by the file (`ops.yaml` is `ops`), and `--replace` puts it over the one of that name, for a shipped file edited since it was seeded. `ai evals export` prints one back, as it was written:

```bash
uv run my-app ai evals export ops > evals/ops.yaml      # ship one written in the app
uv run my-app ai evals import --replace evals/ops.yaml  # an edited file over its row
```

## Evaluators

| Evaluator | Passes when |
|-----------|-------------|
| `ToolCalls: {tool, times, args}` | `tool` was called `times` times, or at least once if `times` is unset. With `args`, only calls holding every one of them count, and `times: 0` means it never was. |
| `ToolOrder: {tools}` | `tools` were called in this order, with other calls allowed between them. |
| `AnswerAvoids: {terms}` | The answer contains none of `terms`, in any case. |
| `Judged: {rubric}` | The model in force says the answer meets `rubric`, given the message and what the turn read (each tool call and its result), so a fact the answer read is not taken for invented. |

`Judged` and Pydantic Evals' `LLMJudge` need a model, so a scripted run leaves them out: no model plays the script, and none grades it. A real run asks the judge too, so a dataset that uses it costs more on every run. Its calls appear in AI spend as `eval_judge`. The judge is the `eval-judge` agent, seeded with the others, so its model and prompt are set in Agents. Until a model is picked there, it runs on the active one. A judge that errors fails its case, never the run. On the memory backend, which keeps no spend, use Pydantic Evals' `LLMJudge` instead.

Pydantic Evals' own evaluators work too, such as `Contains` for something the answer must say. Every check reads in words wherever a run is shown: "calls errors at least once", `says "backend"`, "a judge agrees: says it cannot see a temperature". A run keeps each check's words as they were when it ran, so editing the dataset later doesn't change what an old run says it checked.

## Scripted or real

A case's `script` is the turn it expects. Each step is one model response, either a tool call or the answer. A script plays in the mode its turn was recorded in: one with a `run_code` step in code mode, one that calls tools directly without it, whatever the agent is set to now. Played as a script, the case runs through the real turn without a model: it's free, it gives the same result every time, and CI runs it. The project's own tests play the starter this way.

Run without a script, each case asks the active model. That costs real money, and it's the run that tells you whether the assistant still does the right thing.

`make evals-ci` plays every shipped dataset (`evals/*.yaml`) from its scripts, and the same test runs in `make check`. A case without a script fails there, so every case a dataset ships needs one. A scripted run leaves out the checks a model grades and the ones that read spans (no model plays a script, and none keeps spans), and a case left with no check fails instead of passing unchecked.

An eval run's turns belong to the user `evals`, so they never mix with a person's. Each turn reads as an admin (the app's health, errors and parts), so only an admin starts a run: the evals API is admins only, and the Overseer's own gate covers its section. A turn is not told what is wrong with the app right now, as a chat turn is: a case scores the same whatever the app's health while it runs.

## Running it

A run is kept, and the CLI, `make evals` and the API run and read the kept runs:

```bash
uv run my-app ai evals run                      # every dataset, on the model in force
uv run my-app ai evals run starter --note "after the prompt change"
uv run my-app ai evals run starter --model gpt-4o-mini
uv run my-app ai evals list                     # kept runs, newest first
uv run my-app ai evals datasets                 # each dataset: what it checks, how many cases
uv run my-app ai evals datasets ops             # one dataset: each case, what it asks and passes on
uv run my-app ai evals delete ops               # delete it, once confirmed (--yes skips the question)
uv run my-app ai evals show 12                  # each case: pass or fail, how long; each failed check and why
uv run my-app ai evals show 12 "reads the letter" # one case: its answer, every check and why, the tools it called
uv run my-app ai evals compare 11 12            # the cases that changed, with their scores
make evals                                      # ai evals run, every dataset
```

`ai evals run` names each case that failed, under it every check that failed (in words) and why, and exits 1. `--scripted` plays the scripts instead of asking a model, and its runs are kept as `ci`. A run uses the model picked in the Overseer, even on a worker that booted before the pick. `--model` stands in for it (on the provider that model needs), except for an agent that pins its own. A model that isn't in the catalog, isn't a chat model, or whose provider has no key is refused before any case runs, the same check `llm use` makes.

| Endpoint | |
|----------|---|
| `POST /api/v1/ai/evals/runs` | `{"dataset", "model"?, "note"?}`: starts the run as a job and returns its `job_id` (202). The run goes to the worker when the stack has one, and runs in the webserver otherwise. `/api/v1/jobs/{id}/events` streams each case as it starts (`3 of 12 · reads the letter`), then the run's id. |
| `POST /api/v1/ai/evals/datasets` | `{"name", "about", "cases"?, "like"?}`: has the model write dataset `name` as a job and returns its `job_id` (202), as `ai evals generate` does. 422 for a name taken or not a dataset name, an `about` under 10 characters, or a count out of range; 404 for an unknown `like`. |
| `POST /api/v1/ai/evals/datasets/import` | `{"name", "text", "replace"?}`: keeps `text` (the YAML) as dataset `name` and returns it read (201), as `ai evals import` does. 422 for a name taken (unless `replace`) or not a dataset name, or YAML that is no dataset. |
| `GET /api/v1/ai/evals/datasets` | Every dataset: what it checks, and each case with what it asks and passes on. One that cannot be read (a check it names has gone) is listed with why, and no cases. `/datasets/{name}` reads one (404 for one not there), `/datasets/{name}/yaml` its YAML as written. |
| `DELETE /api/v1/ai/evals/datasets/{name}` | Deletes the dataset (204; 404 for one not there). Its kept runs stay, and the startup seed never brings a shipped one back. |
| `GET /api/v1/ai/evals/runs` | Kept runs, newest first (`?dataset=`, `?model=`, `?limit=`). |
| `GET /api/v1/ai/evals/runs/{id}` | A run and its cases. |
| `GET /api/v1/ai/evals/runs/{id}/cases/{name}` | A case and each evaluator's score. |
| `GET /api/v1/ai/evals/compare?a=&b=` | The cases that changed between two runs, flips first: each with its `change` (`flipped`, `rule changed`, `added` or `removed`), each run's side (passed, answer, cost, time, rules) and every score before and after; `flipped` alone; and `dataset_changed`, whether the dataset differs between them (null when a run didn't record it). |

A run is kept in three tables: `eval_run` (the dataset, the SHA-256 of its YAML, model, build, counts, cost, what started it and a `note` on why), `eval_case` (what each case asked, what came back, what it cost, the tool calls its turn made, or the error that stopped it) and `eval_score` (each evaluator's verdict on a case: 1 or 0 for a pass, or the score itself, and the check's rule in words). Keeping a run deletes its conversations. Runs are small, and nothing deletes them.

From code, `run_evals` scores a dataset and keeps the run, and `eval_runs` reads the kept runs:

```python
from app.core.db import get_async_session
from app.services.ai.service import eval_runs, run_evals

after = await run_evals("starter", note="after the prompt change")
async with get_async_session() as session:
    before = (await eval_runs.runs(session, "starter", limit=2))[-1]
    for case in (await eval_runs.compare(session, before.id, after.id)).cases:
        print(case.name, case.change)
```

## In CI

The generated `.github/workflows/ci.yml` has an `Evals` job that scores every dataset on a real model and fails on a failing case. It runs after `test` passes, on a push or a pull request from the repository itself (a fork's gets no secrets), once the repository names a model under Settings > Secrets and variables > Actions:

| Name | Kind | |
|------|------|---|
| `AI_MODEL` | variable | The model to score on. Without it the job is skipped. |
| `AI_PROVIDER` | variable | Its provider; the first one the project installed otherwise. |
| `<PROVIDER>_API_KEY` | secret | The provider's key, under the name `.env` gives it (`OPENAI_API_KEY`, `OPEN_ROUTER_API_KEY`, `LLM7_API_KEY`...). |
| `EVALS_RUNNER` | variable | The runner (`ubuntu-latest` otherwise). A self-hosted runner beside a local Ollama keeps the run off a paid provider. |
| `OLLAMA_BASE_URL` | variable | Where that runner reaches Ollama, when the project installed it. |

The scripted plays need none of this: they run in the `test` job with the rest of the suite.

## In the Overseer

With the htmx frontend, Overseer > AI > Evals shows the same runs, in three tabs:

- **Datasets:** each dataset in a row: what its leading comment says it checks, how many cases it has and its last run. Opening one shows the model to run it on (the active one unless picked) and "Run N cases", then every case: the message it asks, why it is there, what it passes on in words and how it went in the dataset's last run, opened under its row (the answer, how long it took, each check, the tools it called). "New dataset" has the model write one (a name, what it checks, how many cases, a dataset to write like), keeping the cases that hold, and the tab follows it as it goes. "Import" keeps a YAML file as a dataset named by the file ("Replace" ticked puts it over one of that name), and "Download" on a dataset's page hands back its YAML. "Delete" removes it, once confirmed; its kept runs stay.
- **Runs:** every kept run, newest first, filtered by dataset and model. A run opens on its cases, failed ones first and already open: the message, the whole answer, each check by its rule with a pass or fail mark and why, the tools called summed up ("called errors 4 times, health once") with each call's arguments behind a toggle, and what each case cost. "Compare with the run before" compares it with the last run of the same dataset.
- **Compare:** two runs picked, and only the cases that changed between them: flipped first, then those whose rule changed, then those added and removed. A flip opens on both runs' answers side by side, with each check before and after, and each case shows its cost and time in both. When the dataset changed between the runs (or they ran different datasets), a note says so first. Two runs alike say "No differences."

A started run is the same job as `POST /api/v1/ai/evals/runs`, and its progress shows on the dataset's page and on Runs until it ends. A run kept before rules were recorded shows "rule not recorded" for each check.

With no datasets, the section says how one comes in.

With the observability component and `LOGFIRE_TOKEN` set, a run reports to Logfire as the `evals` process, where each run shows as an evals table. Without a token, it reports nothing.
