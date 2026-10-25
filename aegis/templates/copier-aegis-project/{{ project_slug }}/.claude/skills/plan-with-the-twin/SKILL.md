---
name: plan-with-the-twin
description: Use before planning any change to this project's code. Look up the parts the change involves in the twin (the system model read from the code), run the plan's files past what the twin says they touch, then check the service standard after.
---

# Plan with the twin

The twin is this app's model of itself, read from its code: its parts
(components, services), routes, jobs, tools, tables and Redis keys, and the
edges between them (what calls what, what depends on what, what reads which
table). A plan made from reading files alone finds out what else it touched
only when something breaks. Ask the twin first, check the plan against it,
and check the result against the service standard.

Every command prints JSON or Markdown for a program to read, and runs from a
shell with no server up. The same answers come from the MCP `ontology` tool
when this app's MCP server is connected.

## When to use

Use before planning any change that edits code under `app/`: a feature, a
fix, a refactor, a new route or job.

Do NOT use for a change to docs, config values or tests alone, where no part
of the app changes shape.

## Files that change

None. This skill reads the twin; the change it plans is made by the skill
for that kind of work (`add-api-endpoint`, `add-model-and-migration`, ...).

## Procedure

1. **Find the parts the request names.** List a kind, or search by id:

   ```bash
   uv run python -m app.cli.main ontology find --kind service
   uv run python -m app.cli.main ontology find --text health
   ```

   Kinds: `component`, `service`, `route`, `job`, `tool`, `object` (a
   table), `keys`, `container`, `external`.

2. **Look each one up.** What it is, what it is wired to (its edges and
   neighbours), what is true of it now (health, errors) and its findings
   against the service standard. Several ids go in one ask:

   ```bash
   uv run python -m app.cli.main ontology node component:backend shared:system
   uv run python -m app.cli.main ontology node component:backend --depth 2
   ```

   A part that already has findings is known debt: the plan must not add to
   it.

3. **For a route change, walk the route first.** Every hop it can take,
   read from the code without sending it, each at its file and line:

   ```bash
   uv run python -m app.cli.main ontology route "GET /health/detailed"
   ```

   To see how two parts connect, ask for the paths between them:

   ```bash
   uv run python -m app.cli.main ontology paths component:backend shared:system
   ```

4. **Write the plan, with the files it will touch.**

5. **Run the plan past the twin (the gate).** Give it the plan's files:

   ```bash
   uv run python -m app.cli.main patterns touches app/components/backend/main.py app/services/system/health.py
   ```

   It names the parts those files reach, what depends on them, and the
   tables, routes and jobs in them. Compare with the plan: a part or a
   dependent the plan did not expect is a stop. Rethink the plan, and say in
   it why that part is touched, before editing anything.

6. **Make the change**, following the skill for its kind of work.

7. **Check the service standard after:**

   ```bash
   uv run python -m app.cli.main patterns check $(git diff --name-only)
   ```

   It lists the findings not in `.patterns-baseline.json`, the known debt.
   Fix each new one, or say why not.

## Gates

- `patterns touches` named nothing the plan did not account for.
- `patterns check` lists no new finding left unexplained.

## Pitfalls

- An id is `<kind>:<name>` (`service:auth`, `route:GET /api/v1/...`);
  `ontology find` gives the exact ones. An id the twin does not know is
  refused, with the closest ones it does know.
- A shell builds the twin from the code, with no running server: what is
  true of a part now (health, errors) is read from the stack when it is up,
  and says so when it is not.
- `patterns touches` sees the files given, nothing else: give it every
  file the plan names, tests included, or it answers for less than the
  change.
