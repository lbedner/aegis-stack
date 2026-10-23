"""How a script is written in the sandbox, for an agent in code mode.

Code mode puts an agent's reads inside ``run_code`` (``agent_capabilities``):
it writes one script that calls them, computes, and prints only what the
answer needs. The sandbox is Monty, a strict Python subset, so the rules
it breaks on ride the setting, not a persona: added to the prompt while
code mode is on, whatever the agent's own prompt says.
"""

HEADING = "## SANDBOX RULES"

SANDBOX_RULES = f"""\
{HEADING}

run_code is NOT a REPL. Every call carries a COMPLETE script - fetch,
compute, print - and a typical answer is exactly ONE run_code call
(state persists, so a second run is only for when the first result
genuinely surprises you). Six one-line calls is a defect, not caution.

One complete script looks like:

    found = await errors()
    by_page = {{}}
    for issue in found["issues"]:
        by_page[issue["page"]] = by_page.get(issue["page"], 0) + 1
    print(by_page)

run_code executes Monty, a strict Python subset. Scripts that break these \
rules fail:

- If a run fails, FIX the script and resubmit it WHOLE - never fall back \
to line-at-a-time execution.

- Tools are async: call them with plain top-level `await`. Do not define a \
`main()` wrapper or call `asyncio.run` - top-level await already works.
- Everything is already async - just `await` each tool directly, one \
after another. You never need the `asyncio` MODULE (`gather`, `run`): \
the tools are millisecond reads, so concurrency saves nothing, and \
`asyncio.gather` without its import is this sandbox's most common crash.
- Show results ONLY by print()-ing plain data (strings, numbers, lists, \
dicts). Never end a script on a bare non-data expression such as \
`type(x)` - the tool report cannot carry it. `json.dumps` extras like \
`default=` are unsupported.
- The sandbox's checker does not know `hasattr`/`getattr`/`setattr`; \
use `isinstance(x, dict)` or `.get()` instead. If a script fails with \
a type error, REWRITE the flagged line - do not resubmit it.
- Print only the figures or rows you need, never a whole payload; \
oversized output gets truncated.
- State persists between run_code calls: print a value's shape first, \
then compute against the real keys in the next call."""


def with_sandbox_rules(prompt: str, *, code_mode: bool) -> str:
    """``prompt`` with the sandbox's rules after it while ``code_mode`` is
    on; once, should the prompt carry them already (a row seeded when they
    lived in its persona)."""
    if not code_mode or HEADING in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{SANDBOX_RULES}"
