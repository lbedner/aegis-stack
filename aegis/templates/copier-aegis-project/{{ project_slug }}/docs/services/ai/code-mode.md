# Code Mode

Code mode gives an agent one powerful tool instead of many small ones: the
ability to write a Python script that calls its granted tools as functions,
executed in a sandboxed interpreter. Instead of the model making sequential
tool calls (one round trip each), it writes a single script with loops,
conditionals, and arithmetic, and only returns to the model when the script
finishes.

This is the right shape for questions that need computation over your data.
Language models are unreliable at arithmetic in prose; they are good at
writing the three lines of Python that compute the answer exactly.

## Enabling it for an agent

Code mode is a per-agent grant stored on the agent row, exactly like tool
attachments:

```python
from app.services.ai.domains.chat.agent_registry import update_agent

await update_agent("assistant", {"code_mode": True})
```

The flag hydrates through `resolve_agent` into `AgentConfig.code_mode`, and
`build_chat_agent` then attaches a `CodeMode` capability scoped to exactly
the tools attached to that agent. Nothing changes for agents without the
flag: the capability is never constructed, and the sandbox never loads.

## The security model

Scripts run in [Monty](https://github.com/pydantic/monty), a minimal Python
interpreter built for executing model-written code:

- No filesystem, network, environment, or OS access exists in the sandbox.
- The only way a script touches the outside world is by calling the tools
  the agent was explicitly granted. An agent with no tools can compute, but
  cannot reach anything.
- Results cross the boundary as plain values; host code runs the tools with
  full application access and hands back the return value.

The grant model composes: `code_mode` decides whether scripts run at all,
and the agent's tool attachments decide what those scripts can call.

## Limits to know about

- Monty implements a Python subset: functions, comprehensions, f-strings,
  dataclasses, and async calls work; classes and third-party imports
  (pandas, numpy) do not. Models occasionally reach for an unsupported
  feature; the resulting error is fed back and the model rewrites the
  script within the same turn.
- The per-turn tool-call budget is raised for code-mode agents (16 rather
  than chat's 4) because the working loop is script, observe, script. Pass
  `tool_calls_limit` to `build_chat_agent` to override either default.
- Tool results must be JSON-safe values (dicts, lists, strings, numbers)
  to traverse the sandbox cleanly. Prefer cents-integer money fields and
  ISO date strings over model objects.

## When to prefer plain tool calls

Code mode earns its keep when the answer requires combining or computing
over data. For a single lookup ("what is my balance") a plain tool call is
one round trip and needs no sandbox. Keep conversational agents unflagged
and grant `code_mode` to the agents whose job is analysis.
