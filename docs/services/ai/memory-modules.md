# Memory Modules

Memory modules are reusable prompt-context blocks that agents opt into. Each module can carry **static text** (rules, guidance, framing that never changes), a **dynamic fetcher** (live, per-user data pulled at request time), or **both**. They are the structured alternative to growing one giant hand-written context builder: each concern lives in its own module, agents pick the modules they need, and a token budget keeps the total in check.

Modules require a persistence backend (`ai[sqlite]` or `ai[postgres]`).

## The Hybrid Model

A module row has two independent content columns; assembly is column-driven:

| Columns set | Behavior |
|---|---|
| `prompt_content` only | Static block, injected verbatim |
| `fetch_function` only | Live data from the named fetcher |
| Both | Hybrid: static block first, then the live data |

There is deliberately no "type" field. Whether a module is static, dynamic, or hybrid is simply which columns are filled, so promoting a static module to hybrid is filling one more column, not a migration.

Modules render as the caller: a fetcher that asks whether the caller is an admin gets the answer for whoever is chatting. A typed turn and a live voice call build the agent through one function, so a call holds the same modules, contexts and tools as a typed turn.

### Module fields

| Field | Meaning |
|---|---|
| `slug` | Unique identifier; agents reference modules by slug |
| `context_key` | The label the rendered block carries in the prompt (defaults to the slug) |
| `prompt_content` | Optional static text |
| `fetch_function` | Optional name of a registered fetcher |
| `supports_days_back`, `default_days_back` | Whether and how far the fetcher looks back |
| `priority` | Render order; lower renders first and wins budget contention |
| `token_estimate` | Optional explicit size; `0` means estimate from rendered content |
| `is_active` | Inactive modules are skipped |

A module must have `prompt_content`, `fetch_function`, or both; creating or editing one into an empty state is rejected.

## The App Map

The default `assistant` always has one module, `app_map`, seeded with the agent: what the app is, read from its code. It lists each top-level part with what it is for, the tables by owner with the tables each links to, and the changes an agent may propose. An admin's map includes the parts; anyone else's is the tables and changes alone, as the `ontology` tool answers each. It carries nothing live (no traffic, health or row counts), so its text stays the same turn to turn and a provider's prompt cache serves it. The `ontology` tool stays for depth: one node, its neighbours, the paths between two. Another agent opts in by adding `app_map` to its `memory_modules`.

## Writing a Fetcher

Fetchers are plain async functions registered by name, exactly like tools. The framework ships the registry plus three fetchers: `recent_conversations`, a `user_profile` stub meant to be replaced, and `app_map`. Your application registers its own domain fetchers:

```python
from app.services.ai.fetchers import FetchContext, register_fetcher


async def fetch_open_orders(ctx: FetchContext) -> str | None:
    """Summarize the user's open orders for the prompt."""
    # ctx.user_id  - who the conversation is with
    # ctx.days_back - the module's lookback window, when it supports one
    orders = await load_open_orders(ctx.user_id, days_back=ctx.days_back)
    if not orders:
        return None  # contribute nothing this turn
    lines = "\n".join(f"- {order.summary}" for order in orders)
    return f"Open orders:\n{lines}"


register_fetcher("fetch_open_orders", fetch_open_orders)
```

Then create a module that uses it:

```python
from app.services.ai.memory_modules import create_memory_module

await create_memory_module(
    slug="open-orders",
    name="Open Orders",
    prompt_content="When the user asks about orders, use the live list below.",
    fetch_function="fetch_open_orders",
    supports_days_back=True,
    default_days_back=30,
    priority=50,
    session=session,
)
```

Finally, add `"open-orders"` to an agent's `memory_modules` list. Every chat with that agent now renders:

```
<module name="open-orders">
When the user asks about orders, use the live list below.

Open orders:
- ...
</module>
```

### Failure behavior

Stale data must never break a chat turn:

- A module slug an agent references but no row defines: skipped with a warning.
- A `fetch_function` with no registered callable: that module's dynamic half is skipped with a warning.
- A fetcher that raises: same, logged and skipped.
- A fetcher returning `None`: the module contributes only its static half (or nothing).

## Priority and Token Budget

Modules render in priority order (lower number first). When a token budget is set, higher-priority modules claim it first and any module that does not fit the remaining budget is dropped, with a warning naming it. Hybrid modules are budgeted on **both** halves: the estimate covers the static text plus the fetched data, so a module cannot sneak past the budget on its static half alone. Set `token_estimate` on the row for an exact figure; leave it at `0` to estimate from the rendered content.

## Inspecting Modules

```bash
my-app memory-modules list    # slug, kind, priority, active
my-app memory-modules show open-orders
```

## Related Pages

- [Agent Registry](agents.md): how agents opt into modules
- [Illiana](illiana.md): the built-in assistant persona that modules extend
