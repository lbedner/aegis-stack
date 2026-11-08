# Evals

An eval asks the assistant something and checks what it did. A case is a message and the assertions you wish you'd had when you found a regression by reading logs. A case scores the **tools** the turn called first, and the prose second.

```bash
aegis init my-app --services "ai[sqlite,evals]"
```

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

```python
from app.services.ai.domains.evals.runner import run_dataset

report = await run_dataset("starter", scripted=True)
report.print()
```

An eval run's conversations belong to the user `evals`, so they never mix with a person's.

With the observability component and `LOGFIRE_TOKEN` set, a run reports to Logfire as the `evals` process, where each run shows as an evals table. Without a token, it reports nothing.
