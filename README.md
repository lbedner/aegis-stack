<div align="center" markdown>

<img src="docs/images/aegis_stack_banner.png" alt="Aegis Stack" width="600">

*Inspired by the Neverwinter Nights toolset, Project Zero Dawn, and Dr. Wily.*

[![CI](https://github.com/lbedner/aegis-stack/workflows/CI/badge.svg)](https://github.com/lbedner/aegis-stack/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-aegis--stack.io-17CCBF)](https://docs.aegis-stack.io)
[![PyPI](https://img.shields.io/pypi/v/aegis-stack)](https://pypi.org/project/aegis-stack/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/lbedner/aegis-stack/blob/main/LICENSE)
<br>
[![Monthly Downloads](https://img.shields.io/pypi/dm/aegis-stack)](https://pypi.org/project/aegis-stack/)
[![Total Downloads](https://static.pepy.tech/badge/aegis-stack)](https://pepy.tech/project/aegis-stack)
[![Commits per Month](https://img.shields.io/github/commit-activity/m/lbedner/aegis-stack)](https://github.com/lbedner/aegis-stack/commits)
[![Total Commits](https://img.shields.io/github/commit-activity/t/lbedner/aegis-stack)](https://github.com/lbedner/aegis-stack/commits)
[![Last Commit](https://img.shields.io/github/last-commit/lbedner/aegis-stack)](https://github.com/lbedner/aegis-stack/commits)
<br>
[![Astral](https://img.shields.io/badge/Astral-261230?logo=astral&logoColor=D7FF64)](https://astral.sh)
[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Flet](https://img.shields.io/badge/Flet-24292F?logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHhtbDpzcGFjZT0icHJlc2VydmUiIHdpZHRoPSIzMDdweCIgaGVpZ2h0PSIzMDdweCIgdmVyc2lvbj0iMS4xIiBzaGFwZS1yZW5kZXJpbmc9Imdlb21ldHJpY1ByZWNpc2lvbiIgdGV4dC1yZW5kZXJpbmc9Imdlb21ldHJpY1ByZWNpc2lvbiIgaW1hZ2UtcmVuZGVyaW5nPSJvcHRpbWl6ZVF1YWxpdHkiIGZpbGwtcnVsZT0iZXZlbm9kZCIgY2xpcC1ydWxlPSJldmVub2RkIiB2aWV3Qm94PSIwIDAgMjg1IDI4NSIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiPjxnIGlkPSJMYXllcl94MDAyMF8xIj48cmVjdCBmaWxsPSJub25lIiB3aWR0aD0iMjg1IiBoZWlnaHQ9IjI4NSIgcng9IjkuMDMiIHJ5PSI4LjEyIi8%2BPHBhdGggZmlsbD0iI0VFMzE2NyIgZD0iTTM5LjI4IDE0NC43NGMtMC44NSwtMS41MiAtMC42NiwtMi42MSAwLjEsLTQuMTMgMzEuNDEsLTU4LjM2IDc4LjgxLC05NC4xNSAxMzguNTMsLTExOS43NSAyLjAzLC0wLjg2IDUuMDQsMS41MiA0LjMxLDMuNjUgLTguOSwyNS45MSAtMTUuMTgsNTEuMTMgLTE4LjgyLDc4LjIzIC0zLjMyLDI0Ljk3IC00LjI0LDUwLjc5IC0wLjg3LDc3Ljc3IDMuNTYsMzAuNTkgMTAuODgsNTUuOTkgMTkuNjgsODMuMzYgMC45OCwzLjA1IC0yLjE0LDQuNDMgLTQuNTEsMy4yNiAtNjIuMTksLTMwLjYxIC0xMDkuMzMsLTcwLjY1IC0xMzguNDIsLTEyMi4zOXoiLz48cGF0aCBmaWxsPSIjMDA5OERBIiBmaWxsLW9wYWNpdHk9IjAuNjM5MjE2IiBkPSJNMjI0LjUzIDE5OC41OWMtMzQuMzksLTEwLjc5IC02NS4xNSwtMjkuMDYgLTkyLjQsLTUzLjIgLTEuODIsLTEuNjIgLTEuNjEsLTMuODcgMC4wMywtNS40NCAyNy4wNywtMjUuODggNTcuNzksLTQ2LjE5IDkxLjc0LC02MC41NiAyLjk5LC0xLjI3IDUuNDUsMS4yIDQuNTYsNC42MiAtOS42MiwzNi45MSAtMTEuNzQsNzMuMzkgMC4xMywxMDkuOTUgMC45OCwzLjA1IC0xLjQ3LDUuNDQgLTQuMDYsNC42M3oiLz48cGF0aCBmaWxsPSIjNUFCQUU3IiBkPSJNMjI0LjUzIDE5OC41OWMtMjIuNjQsLTcuMSAtNDMuNzEsLTE3LjQ1IC02My4yNCwtMzAuNTggLTEuMzUsLTIwLjkgLTEuNDcsLTMwLjIgMC43MywtNTMuMjYgMTkuMTksLTE0LjIyIDM5Ljg2LC0yNi4wNCA2MS44OCwtMzUuMzYgMi45OSwtMS4yNyA1LjQ1LDEuMiA0LjU2LDQuNjIgLTkuNjIsMzYuOTEgLTExLjc0LDczLjM5IDAuMTMsMTA5Ljk1IDAuOTgsMy4wNSAtMS40Nyw1LjQ0IC00LjA2LDQuNjN6Ii8%2BPC9nPjwvc3ZnPg%3D%3D)](https://flet.dev)
[![HTMX](https://img.shields.io/badge/htmx-3366CC?logo=htmx&logoColor=white)](https://htmx.org)
[![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?logo=langchain&logoColor=white)](https://www.langchain.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=white)](https://pydantic.dev/docs/)

## Full-stack Python apps that know what they are.

</div>

Aegis Stack gives you a complete FastAPI app, wired and running: API, workers, scheduler, database, auth and AI, with plugins for anything else. Alongside it is [the Twin](https://docs.aegis-stack.io/overseer/twin/), a model of that app taken from its code and its live state. [Overseer](https://docs.aegis-stack.io/overseer/) shows it live and lets you operate it, [Illiana](https://docs.aegis-stack.io/services/ai/illiana/) explains it, and CI catches changes that break its rules, whether you wrote them or your agents did.

![Aegis Stack: a stack made, started, and asked about itself in Overseer](docs/images/aegis-hero.webp)

<!-- cards -->
<table>
<tr>
<td width="50%" valign="top" markdown>

#### Build

**An app.** Build from a [blueprint](https://docs.aegis-stack.io/cli-reference/#aegis-blueprints) or pick your pieces. Add or remove them later; your changes are merged, not overwritten.

</td>
<td width="50%" valign="top" markdown>

#### Ship

**A server.** One command, or one button in Overseer, [provisions a server](https://docs.aegis-stack.io/deployment/cloud/) in your own Hetzner or DigitalOcean account, adds HTTPS, and deploys. The server, the bill, and the data stay yours.

</td>
</tr>
<tr>
<td width="50%" valign="top" markdown>

#### See

**A control plane.** A live map of your system, from the whole stack down to a single function, with errors, deploys, jobs, resources, and cost on the same map. See [Overseer](https://docs.aegis-stack.io/overseer/). The same data is in your app's CLI and, for your agents, over MCP.

</td>
<td width="50%" valign="top" markdown>

#### Ask

**An operator, if you want one.** Talk to [Illiana](https://docs.aegis-stack.io/services/ai/illiana/) or type. She reads that map, answers with diagrams instead of guesses, and reviews every pull request against the system's rules.

</td>
</tr>
</table>
<!-- /cards -->

### What you could build

Each is `uvx aegis-stack init my-app` with:

| Build | With |
|---|---|
| [A SaaS MVP with billing](https://docs.aegis-stack.io/services/payment/) | `-s auth,payment -c database,htmx,worker` |
| [A finance app with an MCP server](https://docs.aegis-stack.io/services/finance/) | `-b finance -c database,scheduler,worker,mcp` |
| [A voice agent for your meetings](https://docs.aegis-stack.io/services/meetings/) | `-s "meetings,ai[sqlite,voice]"` |
| [A document vault, read by AI](https://docs.aegis-stack.io/services/documents/) | `-s auth,documents,ai -c database,storage,worker` |
| [A local AI app on Ollama](https://docs.aegis-stack.io/components/inference/) | `-s "ai[ollama]"` |

<details class="more" markdown>
<summary>5 more</summary>

| Build | With |
|---|---|
| [Email, SMS and calls from your app](https://docs.aegis-stack.io/services/comms/) | `-s comms -c worker` |
| [A Markdown blog with an editor](https://docs.aegis-stack.io/services/blog/) | `-s blog` |
| [A tracker for posts on your topic](https://docs.aegis-stack.io/services/research/) | `-s research -c database,scheduler` |
| [Adoption analytics](https://docs.aegis-stack.io/services/insights/) | `-s "insights[github,pypi]"` |
| [Background jobs at scale](https://docs.aegis-stack.io/components/worker/) | `-c worker,scheduler` |

</details>

### Running on it

| Live | What it is |
|---|---|
| **[Aegis Pulse](https://pulse.aegis-stack.io/)** | Package analytics with honest decomposition (total, filtered, human) |
| **[Sector 7G](https://sector-7g.dev/dashboard/)** | Millions of tasks on a single $5 VPS, zero restarts |
| **[NWVault Revival](http://167.99.48.44/)** | A searchable archive of the original Neverwinter Vault (2002-2014), built in 24 hours |

## Quick Start

```bash
uvx aegis-stack init my-app
```

`init` opens a full-screen guided setup that walks through every component and service with explanations. Prefer the classic one-line prompts? Pass `--quick`.

<details>
<summary><strong>More examples</strong></summary>

```bash
# Skip the guided setup, use the classic one-line prompts
uvx aegis-stack init my-app --quick

# Add user authentication out of the box
uvx aegis-stack init user-app --services auth

# Add background processing + scheduling
uvx aegis-stack init task-processor --components scheduler,worker

# Everything wired up at init
uvx aegis-stack init full-app --services auth,payment,comms --components worker,scheduler
```

</details>

> **CLI in 9 languages:** English, German, Spanish, French, Japanese, Korean, Russian, Simplified Chinese, Traditional Chinese. Run e.g. `uvx aegis-stack --lang zh init my-app`, or set `AEGIS_LANG=zh`.

**Installation alternatives:** See the [Installation Guide](https://docs.aegis-stack.io/installation/) for `uv tool install`, `pip install`, and development setup.

## Customizing Your Stack

![Aegis Stack spinning up a new project](docs/images/aegis-spinup-demo.webp)

**Components** are infrastructure pieces (database, workers, scheduler, cache). **Services** are business capabilities (auth, AI, payments, comms).

**Don't worry about what you pick today.** Add anything later with a single command and remove what you outgrow. Where a change touches files you've edited, your edits are merged in, and anything that can't merge cleanly is marked for you to review.

```bash
# Monday: Ship MVP
aegis init my-app

# Week 3: Add scheduled reports
aegis add scheduler --project-path ./my-app

# Month 2: Need async workers
aegis add worker --project-path ./my-app

# Month 6: Scheduler not needed
aegis remove scheduler --project-path ./my-app

# Stay current with template improvements
aegis update
```

See **[Evolving Your Stack](https://docs.aegis-stack.io/evolving-your-stack/)** for the complete guide.

### Components

<!-- aegis:components -->
| Component | What you get | |
|---|---|---|
| **[Backend](https://docs.aegis-stack.io/components/backend/)** | FastAPI on uvicorn or granian, lifecycle hooks, in-memory request metrics, API load testing for every route | ![Always](https://img.shields.io/badge/-always_on-2ea043) |
| **[CLI](https://docs.aegis-stack.io/cli-reference/)** | Typer, first-class system interface | ![Always](https://img.shields.io/badge/-always_on-2ea043) |
| **[Frontend](https://docs.aegis-stack.io/components/frontend/)** | Flet, ships with the Overseer system dashboard | ![Always](https://img.shields.io/badge/-always_on-2ea043) |
| **[Browser](https://docs.aegis-stack.io/components/browser/)** | Remote Chromium in its own container, driven over Playwright: JavaScript pages, sign-ins, a bot that joins a meeting | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Database](https://docs.aegis-stack.io/components/database/)** | Postgres (self-hosted or Neon serverless) or SQLite + SQLModel ORM | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Deploy](https://docs.aegis-stack.io/components/deploy/)** | Deployment target (Docker Compose), read by the Overseer | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Inference](https://docs.aegis-stack.io/components/inference/)** | Local AI models via Ollama, speech via Kokoro | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Ingress](https://docs.aegis-stack.io/components/ingress/)** | Traefik v3 reverse proxy with TLS | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[MCP](https://docs.aegis-stack.io/components/mcp/)** | Serves the app's own tools to Claude Desktop, Claude Code or a local model over MCP: the tools you grant, never a write | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Observability](https://docs.aegis-stack.io/components/observability/)** | Pydantic Logfire tracing + metrics + logging | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Redis](https://docs.aegis-stack.io/components/redis/)** | Redis for caching, sessions, pub/sub | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Scheduler](https://docs.aegis-stack.io/components/scheduler/)** | APScheduler with persistent jobs | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Secrets](https://docs.aegis-stack.io/components/secrets/)** | Encrypted credential store: keys set while the app runs, checked with the provider on paste, never shown again | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Storage](https://docs.aegis-stack.io/components/storage/)** | S3 object storage for the files an app keeps, SeaweedFS in dev | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Web Frontend](https://docs.aegis-stack.io/components/web-frontend/)** | Server-rendered pages at `/`: Jinja2 + htmx + Alpine, Tailwind/DaisyUI styling | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Worker](https://docs.aegis-stack.io/components/worker/)** | Pluggable Arq, Taskiq, or Dramatiq | ![Optional](https://img.shields.io/badge/-optional-blue) |
<!-- /aegis:components -->

[Components Docs →](https://docs.aegis-stack.io/components/)

### Services

<!-- aegis:services -->
| Service | What you get | |
|---|---|---|
| **[AI](https://docs.aegis-stack.io/services/ai/)** | Conversational agents, RAG, model catalog, TTS and STT (PydanticAI / LangChain across 7 providers) | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Auth](https://docs.aegis-stack.io/services/auth/)** | Persistent sessions with refresh-token rotation, GitHub/Google sign-in, RBAC, multi-tenant Organizations | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Blog](https://docs.aegis-stack.io/services/blog/)** | Markdown publishing with drafts, tags, and an Overseer editor | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Comms](https://docs.aegis-stack.io/services/comms/)** | Transactional email (Resend) + SMS / voice (Twilio) | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Documents](https://docs.aegis-stack.io/services/documents/)** | Content-addressed document store, deduped, with page-addressed extraction | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Finance](https://docs.aegis-stack.io/services/finance/)** | Personal finance aggregation (accounts, transactions, net worth, import) | ![Optional](https://img.shields.io/badge/-optional-blue) ![Experimental](https://img.shields.io/badge/-experimental-orange) |
| **[Insights](https://docs.aegis-stack.io/services/insights/)** | Adoption metrics across GitHub, PyPI, Plausible, Reddit | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Meetings](https://docs.aegis-stack.io/services/meetings/)** | A bot that joins Google Meet as its own agent: transcript, notes, threads, people, what keeps coming up, joined from its calendar | ![Optional](https://img.shields.io/badge/-optional-blue) ![Experimental](https://img.shields.io/badge/-experimental-orange) |
| **[Payment](https://docs.aegis-stack.io/services/payment/)** | Stripe checkout, subscriptions, refunds, disputes | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Research](https://docs.aegis-stack.io/services/research/)** | Outside posts and threads, collected by saved searches | ![Optional](https://img.shields.io/badge/-optional-blue) |
<!-- /aegis:services -->

[Services Docs →](https://docs.aegis-stack.io/services/)

### Plugins

What the built-in services don't cover can come from a plugin: a Python package that adds routes, tables, a CLI and a dashboard card, and goes in and out the same way (`aegis add <name>`, `aegis remove <name>`). Browse them at [aegis-stack.io/plugins](https://aegis-stack.io/plugins) or with `aegis plugins search`, and start your own with `aegis plugins create`.

[Plugins Docs →](https://docs.aegis-stack.io/plugins/)

## Deploy and back up

- **Provision** a server in your own Hetzner or DigitalOcean account, price shown first, with `aegis deploy-provision` or from Overseer > Deployments. HTTPS comes with it.
- **Deploy** to any VPS over SSH with `aegis deploy`: rsync and Docker, no PaaS lock-in.
- **Back up** before every deploy, roll back on a failed health check, keep encrypted nightly copies off the server, and run a drill that proves they restore.
- **CI** on every push: GitHub Actions for lint, types and tests, CodeQL scanning, and an optional continuous-deploy workflow.

[Deployment Docs →](https://docs.aegis-stack.io/deployment/)

## Integrations

Aegis Stack is the orchestration layer. Services and components wire into best-in-class tools you already trust, so you keep your vendor choices and your data.

<table width="100%">
<tr>
<td align="center" width="16.66%"><a href="https://www.anthropic.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/anthropic-dark.svg"><img src="docs/images/integrations/anthropic.svg" loading="lazy" style="height:32px;width:auto" alt="Anthropic" title="Anthropic: AI provider" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://astral.sh"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/astral-dark.svg"><img src="docs/images/integrations/astral.svg" loading="lazy" style="height:32px;width:auto" alt="Astral" title="Astral: ruff, uv, ty, uvx toolchain" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://www.trychroma.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/chromadb-dark.svg"><img src="docs/images/integrations/chromadb.svg" loading="lazy" style="height:32px;width:auto" alt="ChromaDB" title="ChromaDB: Vector store for AI service" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://dramatiq.io"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/dramatiq-dark.png"><img src="docs/images/integrations/dramatiq.png" loading="lazy" style="height:32px;width:auto" alt="Dramatiq" title="Dramatiq: Worker backend" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://fastapi.tiangolo.com"><img src="docs/images/integrations/fastapi.svg" loading="lazy" style="height:32px;width:auto" alt="FastAPI" title="FastAPI: Backend web framework" /></a></td>
<td align="center" width="16.66%"><a href="https://flet.dev"><img src="docs/images/integrations/flet.svg" loading="lazy" style="height:32px;width:auto" alt="Flet" title="Flet: Frontend framework" /></a></td>
</tr>
<tr>
<td align="center" width="16.66%"><a href="https://github.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/github-dark.svg"><img src="docs/images/integrations/github.svg" loading="lazy" style="height:32px;width:auto" alt="GitHub" title="GitHub: OAuth provider" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://www.google.com"><img src="docs/images/integrations/google.svg" loading="lazy" style="height:32px;width:auto" alt="Google" title="Google: AI provider and OAuth" /></a></td>
<td align="center" width="16.66%"><a href="https://github.com/remsky/Kokoro-FastAPI"><img src="docs/images/integrations/kokoro.png" loading="lazy" style="height:32px;width:auto" alt="Kokoro" title="Kokoro: Local text-to-speech (Kokoro-FastAPI)" /></a></td>
<td align="center" width="16.66%"><a href="https://www.langchain.com"><img src="docs/images/integrations/langchain.png" loading="lazy" style="height:32px;width:auto" alt="LangChain" title="LangChain: AI provider abstraction" /></a></td>
<td align="center" width="16.66%"><a href="https://neon.tech"><img src="docs/images/integrations/neon.svg" loading="lazy" style="height:32px;width:auto" alt="Neon" title="Neon: Serverless Postgres, database provider" /></a></td>
<td align="center" width="16.66%"><a href="https://ollama.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/ollama-dark.svg"><img src="docs/images/integrations/ollama.svg" loading="lazy" style="height:32px;width:auto" alt="Ollama" title="Ollama: Local LLM runtime" /></picture></a></td>
</tr>
<tr>
<td align="center" width="16.66%"><a href="https://plausible.io"><img src="docs/images/integrations/plausibleanalytics.svg" loading="lazy" style="height:32px;width:auto" alt="Plausible" title="Plausible: Analytics source for Insights service" /></a></td>
<td align="center" width="16.66%"><a href="https://www.postgresql.org"><img src="docs/images/integrations/postgresql.svg" loading="lazy" style="height:32px;width:auto" alt="Postgres" title="Postgres: Database component" /></a></td>
<td align="center" width="16.66%"><a href="https://pydantic.dev"><img src="docs/images/integrations/pydantic.svg" loading="lazy" style="height:32px;width:auto" alt="Pydantic" title="Pydantic: validation, Pydantic AI, Logfire (observability)" /></a></td>
<td align="center" width="16.66%"><a href="https://www.reddit.com"><img src="docs/images/integrations/reddit.svg" loading="lazy" style="height:32px;width:auto" alt="Reddit" title="Reddit: Insights service signal source" /></a></td>
<td align="center" width="16.66%"><a href="https://redis.io"><img src="docs/images/integrations/redis.svg" loading="lazy" style="height:32px;width:auto" alt="Redis" title="Redis: Cache component, worker queue backing" /></a></td>
<td align="center" width="16.66%"><a href="https://resend.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/resend-dark.svg"><img src="docs/images/integrations/resend.svg" loading="lazy" style="height:32px;width:auto" alt="Resend" title="Resend: Transactional email" /></picture></a></td>
</tr>
<tr>
<td align="center" width="16.66%"><a href="https://www.sqlite.org"><img src="docs/images/integrations/sqlite.svg" loading="lazy" style="height:32px;width:auto" alt="SQLite" title="SQLite: Database component (default)" /></a></td>
<td align="center" width="16.66%"><a href="https://stripe.com"><img src="docs/images/integrations/stripe.svg" loading="lazy" style="height:32px;width:auto" alt="Stripe" title="Stripe: Payments service" /></a></td>
<td align="center" width="16.66%"><a href="https://supabase.com"><img src="docs/images/integrations/supabase.svg" loading="lazy" style="height:32px;width:auto" alt="Supabase" title="Supabase: Auth backend and hosted Postgres (planned)" /></a></td>
<td align="center" width="16.66%"><a href="https://taskiq-python.github.io"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/taskiq-dark.svg"><img src="docs/images/integrations/taskiq.svg" loading="lazy" style="height:32px;width:auto" alt="Taskiq" title="Taskiq: Worker backend" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://traefik.io"><img src="docs/images/integrations/traefikproxy.svg" loading="lazy" style="height:32px;width:auto" alt="Traefik" title="Traefik: Ingress and reverse proxy" /></a></td>
<td align="center" width="16.66%"><a href="https://www.twilio.com"><img src="docs/images/integrations/twilio.svg" loading="lazy" style="height:32px;width:auto" alt="Twilio" title="Twilio: SMS and voice for Comms service" /></a></td>
</tr>
<tr>
<td align="center" width="16.66%"><a href="https://typer.tiangolo.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/typer-dark.svg"><img src="docs/images/integrations/typer.svg" loading="lazy" style="height:32px;width:auto" alt="Typer" title="Typer: CLI framework" /></picture></a></td>
</tr>
</table>

## For The Veterans

<img src="docs/images/ron-swanson.webp" alt="Ron Swanson" width="480">

No reinventing the wheel. It's FastAPI, SQLModel, Pydantic and the rest of the tools you already know, wired together and ready to compose.

No custom abstractions or proprietary framework to learn. Once your stack is generated, it's your code: build it however you want. The Twin reads the code as it is; it doesn't ask you to write it a special way.

Aegis gets out of your way so you can get started.
