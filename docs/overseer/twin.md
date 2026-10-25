# The Twin

The Twin is a model of your app that stays true to it: built from its code, and kept in step with it as it runs. Nobody writes or maintains it. Overseer draws it, Illiana and MCP clients read it through their tools, and the API serves it as JSON.

It has five layers, each saying something more certain than the one above it:

| Layer | Says | Read from | Where you see it |
|---|---|---|---|
| **Ontology** | What exists: every part, route, table, job, worker queue and task, and tool, and how they connect | The source code | The map, `GET /api/v1/ontology`, the `ontology` tool, `<app> ontology find`, `node`, `paths`, `export` |
| **Dry paths** | What could happen: every way a route can go, before it ever runs | The source code | A route's dry path on Overseer's Server page, the `ontology` tool, `<app> ontology route` |
| **Live state** | What is: each part's health, errors, spend and memory, when asked | The running stack | The map's status, the `health` and `errors` tools, a node's `now` |
| **Observed calls** | What does happen: the calls actually made between parts, how often and how long | Requests as they run | The map's edges and heat |
| **Recorded requests** | What did happen: one real request, hop by hop, at its real timing | The last 200 requests, kept a day | Overseer's replay, `GET /api/v1/requests`, the `requests` tool |

The ontology is the Twin's vocabulary, the nouns and verbs every other layer is named in: a hop in a recorded request goes through `service:auth` and `component:database` because the ontology names them so.

## Zoom

Every layer reads at any zoom, the way a C4 diagram does:

```
            Context ....... Container ....... Component ........ Code
            the stack,      backend, db,      services and      file:line
            what it calls   redis, worker     their pieces
          +-----------------------------------------------------------+
Ontology  | what exists                                               |
Dry paths | what could happen                                         |
Live      | what is                                                   |
Observed  | what does happen                                          |
Recorded  | what did happen                                           |
          +-----------------------------------------------------------+
                  one typed read: frozen Pydantic models
                  /                 |                  \
           Overseer map       Illiana's tools      MCP, the API
```

Overseer's map starts at the Server (containers), opens a service into its pieces (components), and links each hop to the lines of code it ran through.

## One read for every reader

Overseer, Illiana and the API read the same models (`frozen`, `extra="forbid"`), so a request is described the same way on the replay page, in Illiana's answer and in the JSON: a part by its ontology id, a line of code by its path, line, service and piece.

## From a shell

A coding agent (or you) asks the Twin from the app's CLI, with no server up: the same answers the `ontology` tool gives Illiana and MCP clients, as JSON, built with the app so its routes are in them.

```bash
uv run <app> ontology find --kind service           # the parts of a kind, or --text to search ids
uv run <app> ontology node component:backend        # a part, its edges and neighbours, its live state
uv run <app> ontology paths component:backend shared:system
uv run <app> ontology route "GET /health/detailed"  # every hop a route can take, at its file and line
uv run <app> patterns touches app/services/system/health.py   # what a change's files reach
```

Every generated app ships the `plan-with-the-twin` skill (`.claude/skills/`): before planning a change, a coding agent looks up the parts involved, runs its plan's files past `patterns touches`, and checks the service standard with `patterns check` after.
