# Evals

An eval asks the assistant something and checks what it did. A case is a message and the assertions you wish you'd had when you found a regression by reading logs. A case scores the **tools** the turn called first, and the prose second.

```bash
aegis init my-app --services "ai[sqlite,evals]"
```

To add it to an existing project, name the backend it already has, so the brackets don't ask for a different one: `aegis add-service "ai[sqlite,evals]"`.

Evals need Pydantic AI. On LangChain the option ships nothing, because LangChain's turns record no tool calls to score.

## A dataset

Datasets live in `evals/<name>.yaml`. A new project gets `evals/starter.yaml`:

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

`inputs.agent` asks a named agent instead of the default.

## Evaluators

| Evaluator | Passes when |
|-----------|-------------|
| `ToolCalls: {tool, times, args}` | `tool` was called `times` times, or at least once if `times` is unset. With `args`, only calls holding every one of them count, and `times: 0` means it never was. |
| `ToolOrder: {tools}` | `tools` were called in this order, with other calls allowed between them. |
| `AnswerAvoids: {terms}` | The answer contains none of `terms`, in any case. |
| `Judged: {rubric}` | The model in force says the answer meets `rubric`, given the message. |

`Judged` asks a model even when the case plays a script, so a dataset that uses it costs money on every run. Its calls appear in AI spend as `eval_judge`. The judge is the `eval-judge` agent, seeded with the others, so its model and prompt are set in Agents. Until a model is picked there, it runs on the active one. A judge that errors fails its case, never the run. On the memory backend, which keeps no spend, use Pydantic Evals' `LLMJudge` instead.

Pydantic Evals' own evaluators work too, such as `Contains` for something the answer must say.

## Scripted or real

A case's `script` is the turn it expects. Each step is one model response, either a tool call or the answer. Played as a script, the case runs through the real turn without a model: it's free, it gives the same result every time, and CI runs it. The project's own tests play the starter this way.

Run without a script, each case asks the active model. That costs real money, and it's the run that tells you whether the assistant still does the right thing.

`make evals-ci` plays every dataset under `evals/` from its scripts, and the same test runs in `make check`. A case without a script fails there, so every case a dataset ships needs one.

An eval run's turns belong to the user `evals`, so they never mix with a person's.

## Running it

On a database-backed stack, a run is kept, and the CLI, `make evals` and the API run and read the kept runs:

```bash
uv run my-app ai evals run                      # every dataset, on the model in force
uv run my-app ai evals run starter --note "after the prompt change"
uv run my-app ai evals run starter --model gpt-4o-mini
uv run my-app ai evals list                     # kept runs, newest first
uv run my-app ai evals show 12                  # each case: pass or fail, how long, why it errored
uv run my-app ai evals compare 11 12            # the cases that flipped, with their scores
make evals                                      # ai evals run, every dataset
```

`ai evals run` exits 1 when a case fails. `--scripted` plays the scripts instead of asking a model, and its runs are kept as `ci`. A run uses the model picked in the Overseer, even on a worker that booted before the pick. `--model` stands in for it (on the provider that model needs), except for an agent that pins its own. A model that isn't in the catalog, isn't a chat model, or whose provider has no key is refused before any case runs, the same check `llm use` makes.

| Endpoint | |
|----------|---|
| `POST /api/v1/ai/evals/runs` | `{"dataset", "model"?, "note"?}`: starts the run as a job and returns its `job_id` (202). The run goes to the worker when the stack has one, and runs in the webserver otherwise. `/api/v1/jobs/{id}/events` streams each case as it starts (`3 of 12 · reads the letter`), then the run's id. |
| `GET /api/v1/ai/evals/runs` | Kept runs, newest first (`?dataset=`, `?limit=`). |
| `GET /api/v1/ai/evals/runs/{id}` | A run and its cases. |
| `GET /api/v1/ai/evals/runs/{id}/cases/{name}` | A case and each evaluator's score. |
| `GET /api/v1/ai/evals/compare?a=&b=` | The cases two runs share, and `flipped`: those whose pass or fail changed. |

A run is kept in three tables: `eval_run` (the dataset, model, build, counts, cost, what started it and a `note` on why), `eval_case` (what each case asked, what came back, the tool calls its turn made, or the error that stopped it) and `eval_score` (each evaluator's verdict on a case: 1 or 0 for a pass, or the score itself). Keeping a run deletes its conversations. Runs are small, and nothing deletes them.

From code, `run_evals` scores a dataset and keeps the run, and `eval_runs` reads the kept runs:

```python
from app.core.db import get_async_session
from app.services.ai.service import eval_runs, run_evals

after = await run_evals("starter", note="after the prompt change")
async with get_async_session() as session:
    before = (await eval_runs.runs(session, "starter", limit=2))[-1]
    for case in (await eval_runs.compare(session, before.id, after.id)).flipped:
        print(case.name, case.before, "->", case.after)
```

On the memory backend there is nowhere to keep a run, so there is no CLI, API or `make evals`. `run_dataset` still scores a dataset, and `make evals-ci` still plays the scripts.

With the observability component and `LOGFIRE_TOKEN` set, a run reports to Logfire as the `evals` process, where each run shows as an evals table. Without a token, it reports nothing.
