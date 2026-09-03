<img src="docs/images/aegis_stack_wordmark.svg" alt="Aegis Stack" width="500">

[![CI](https://github.com/lbedner/aegis-stack/workflows/CI/badge.svg)](https://github.com/lbedner/aegis-stack/actions/workflows/ci.yml)
[![Documentation](https://github.com/lbedner/aegis-stack/workflows/Deploy%20Documentation/badge.svg)](https://github.com/lbedner/aegis-stack/actions/workflows/docs.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)
<br>
[![Monthly Downloads](https://img.shields.io/pypi/dm/aegis-stack)](https://pypi.org/project/aegis-stack/)
[![Total Downloads](https://static.pepy.tech/badge/aegis-stack)](https://pepy.tech/project/aegis-stack)
<br>
[![Commits per Month](https://img.shields.io/github/commit-activity/m/lbedner/aegis-stack)](https://github.com/lbedner/aegis-stack/commits)
[![Total Commits](https://img.shields.io/github/commit-activity/t/lbedner/aegis-stack)](https://github.com/lbedner/aegis-stack/commits)
[![Last Commit](https://img.shields.io/github/last-commit/lbedner/aegis-stack)](https://github.com/lbedner/aegis-stack/commits)

**Aegis Stack is an open-source CLI that scaffolds production-ready FastAPI applications and lets you add, remove, and update components and services on existing projects without rewrites.**

You need to ship reliable software, but management only gave you 2 weeks.

No time for health checks, proper testing, or clean architecture. Just enough time for duct tape and hope.

**What if you could go from idea to working prototype in the time it takes to grab coffee?**

![Aegis Stack Quick Start Demo](docs/images/aegis-demo.gif)

**Ship FastAPI apps that grow with you.**

Aegis Stack scaffolds complete FastAPI applications with auth, payments, workers, AI, and a built-in control plane. Add what you need, remove what you don't, update when the framework improves.

## Quick Start

```bash
uvx aegis-stack init my-api
```

`init` opens a full-screen guided setup that walks through every component and service with explanations. Prefer the classic one-line prompts? Pass `--quick`.

<details>
<summary><strong>More examples</strong></summary>

```bash
# Skip the guided setup, use the classic one-line prompts
uvx aegis-stack init my-api --quick

# Add user authentication out of the box
uvx aegis-stack init user-app --services auth

# Add background processing + scheduling
uvx aegis-stack init task-processor --components scheduler,worker

# Everything wired up at init
uvx aegis-stack init full-app --services auth,payment,comms --components worker,scheduler
```

</details>

> **CLI in 9 languages:** English, German, Spanish, French, Japanese, Korean, Russian, Simplified Chinese, Traditional Chinese. Run e.g. `uvx aegis-stack --lang zh init my-api`, or set `AEGIS_LANG=zh`.

**Installation alternatives:** See the [Installation Guide](https://docs.aegis-stack.io/installation/) for `uv tool install`, `pip install`, and development setup.

## Customizing Your Stack

![Aegis Stack spinning up a new project](docs/images/aegis-spinup-demo.gif)

**Components** are infrastructure pieces (database, workers, scheduler, cache). **Services** are business capabilities (auth, AI, payments, comms).

**Don't worry about what you pick today.** Add anything later with a single command, remove what you outgrow, no rework required.

### Components

| Component | What you get | |
|---|---|---|
| **[Backend](https://docs.aegis-stack.io/components/backend/)** | FastAPI + lifecycle hooks, in-memory request metrics, API load testing for every route | ![Always](https://img.shields.io/badge/-always_on-2ea043) |
| **[CLI](https://docs.aegis-stack.io/cli-reference/)** | Typer, first-class system interface | ![Always](https://img.shields.io/badge/-always_on-2ea043) |
| **[Frontend](https://docs.aegis-stack.io/components/frontend/)** | Flet, ships with the Overseer system dashboard | ![Always](https://img.shields.io/badge/-always_on-2ea043) |
| **[Web Frontend](https://docs.aegis-stack.io/components/web-frontend/)** | Server-rendered pages at `/`: Jinja2 + htmx + Alpine, Tailwind/DaisyUI styling | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Cache](https://docs.aegis-stack.io/components/)** | Redis for caching, sessions, pub/sub | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Database](https://docs.aegis-stack.io/components/database/)** | Postgres (self-hosted or Neon serverless) or SQLite + SQLModel ORM | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Inference](https://docs.aegis-stack.io/components/)** | Local AI models via Ollama | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Ingress](https://docs.aegis-stack.io/components/ingress/)** | Traefik v3 reverse proxy with TLS | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Observability](https://docs.aegis-stack.io/components/observability/)** | Pydantic Logfire tracing + metrics + logging | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Storage](https://docs.aegis-stack.io/components/storage/)** | S3 object storage for the files an app keeps, SeaweedFS in dev | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Scheduler](https://docs.aegis-stack.io/components/scheduler/)** | APScheduler with persistent jobs | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Worker](https://docs.aegis-stack.io/components/worker/)** | Pluggable Arq, Taskiq, or Dramatiq | ![Optional](https://img.shields.io/badge/-optional-blue) |

[Components Docs →](https://docs.aegis-stack.io/components/)

### Services

| Service | What you get | |
|---|---|---|
| **[AI](https://docs.aegis-stack.io/services/ai/)** | Conversational agents, RAG, model catalog, TTS and STT (PydanticAI / LangChain across 7 providers) | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Auth](https://docs.aegis-stack.io/services/auth/)** | Persistent sessions with refresh-token rotation, GitHub/Google sign-in, RBAC, multi-tenant Organizations | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Blog](https://docs.aegis-stack.io/services/blog/)** | Markdown publishing with drafts, tags, and an Overseer editor | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Comms](https://docs.aegis-stack.io/services/comms/)** | Transactional email (Resend) + SMS / voice (Twilio) | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Documents](https://docs.aegis-stack.io/services/documents/)** | Content-addressed document store, deduped, with page-addressed extraction | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Insights](https://docs.aegis-stack.io/services/insights/)** | Adoption metrics across GitHub, PyPI, Plausible, Reddit | ![Optional](https://img.shields.io/badge/-optional-blue) |
| **[Payments](https://docs.aegis-stack.io/services/payment/)** | Stripe checkout, subscriptions, refunds, disputes | ![Optional](https://img.shields.io/badge/-optional-blue) |

[Services Docs →](https://docs.aegis-stack.io/services/)

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
<td align="center" width="16.66%"><a href="https://www.langchain.com"><img src="docs/images/integrations/langchain.png" loading="lazy" style="height:32px;width:auto" alt="LangChain" title="LangChain: AI provider abstraction" /></a></td>
<td align="center" width="16.66%"><a href="https://neon.tech"><img src="docs/images/integrations/neon.svg" loading="lazy" style="height:32px;width:auto" alt="Neon" title="Neon: Serverless Postgres, database provider" /></a></td>
<td align="center" width="16.66%"><a href="https://ollama.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/ollama-dark.svg"><img src="docs/images/integrations/ollama.svg" loading="lazy" style="height:32px;width:auto" alt="Ollama" title="Ollama: Local LLM runtime" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://plausible.io"><img src="docs/images/integrations/plausibleanalytics.svg" loading="lazy" style="height:32px;width:auto" alt="Plausible" title="Plausible: Analytics source for Insights service" /></a></td>
</tr>
<tr>
<td align="center" width="16.66%"><a href="https://www.postgresql.org"><img src="docs/images/integrations/postgresql.svg" loading="lazy" style="height:32px;width:auto" alt="Postgres" title="Postgres: Database component" /></a></td>
<td align="center" width="16.66%"><a href="https://pydantic.dev"><img src="docs/images/integrations/pydantic.svg" loading="lazy" style="height:32px;width:auto" alt="Pydantic" title="Pydantic: validation, Pydantic AI, Logfire (observability)" /></a></td>
<td align="center" width="16.66%"><a href="https://www.reddit.com"><img src="docs/images/integrations/reddit.svg" loading="lazy" style="height:32px;width:auto" alt="Reddit" title="Reddit: Insights service signal source" /></a></td>
<td align="center" width="16.66%"><a href="https://redis.io"><img src="docs/images/integrations/redis.svg" loading="lazy" style="height:32px;width:auto" alt="Redis" title="Redis: Cache component, worker queue backing" /></a></td>
<td align="center" width="16.66%"><a href="https://resend.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/resend-dark.svg"><img src="docs/images/integrations/resend.svg" loading="lazy" style="height:32px;width:auto" alt="Resend" title="Resend: Transactional email" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://www.sqlite.org"><img src="docs/images/integrations/sqlite.svg" loading="lazy" style="height:32px;width:auto" alt="SQLite" title="SQLite: Database component (default)" /></a></td>
</tr>
<tr>
<td align="center" width="16.66%"><a href="https://stripe.com"><img src="docs/images/integrations/stripe.svg" loading="lazy" style="height:32px;width:auto" alt="Stripe" title="Stripe: Payments service" /></a></td>
<td align="center" width="16.66%"><a href="https://supabase.com"><img src="docs/images/integrations/supabase.svg" loading="lazy" style="height:32px;width:auto" alt="Supabase" title="Supabase: Auth backend and hosted Postgres (planned)" /></a></td>
<td align="center" width="16.66%"><a href="https://taskiq-python.github.io"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/taskiq-dark.svg"><img src="docs/images/integrations/taskiq.svg" loading="lazy" style="height:32px;width:auto" alt="Taskiq" title="Taskiq: Worker backend" /></picture></a></td>
<td align="center" width="16.66%"><a href="https://traefik.io"><img src="docs/images/integrations/traefikproxy.svg" loading="lazy" style="height:32px;width:auto" alt="Traefik" title="Traefik: Ingress and reverse proxy" /></a></td>
<td align="center" width="16.66%"><a href="https://www.twilio.com"><img src="docs/images/integrations/twilio.svg" loading="lazy" style="height:32px;width:auto" alt="Twilio" title="Twilio: SMS and voice for Comms service" /></a></td>
<td align="center" width="16.66%"><a href="https://typer.tiangolo.com"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/integrations/typer-dark.svg"><img src="docs/images/integrations/typer.svg" loading="lazy" style="height:32px;width:auto" alt="Typer" title="Typer: CLI framework" /></picture></a></td>
</tr>
</table>

## CI/CD for Your Stack

Every generated project ships with GitHub Actions and developer tooling pre-wired, so the first push to GitHub runs checks automatically, and one command wires up continuous deployment to your server.

<table>
<thead>
<tr><th>Capability</th><th>What you get</th><th width="80">Status</th></tr>
</thead>
<tbody>
<tr><td><b>CI Workflow</b></td><td>Lint, type checking, and tests on every push and PR (parallel jobs, cached)</td><td><img src="https://img.shields.io/badge/-available-2ea043" alt="Available" width="64"></td></tr>
<tr><td><b>Code Scanning</b></td><td>CodeQL static analysis on every PR and on a weekly schedule</td><td><img src="https://img.shields.io/badge/-available-2ea043" alt="Available" width="64"></td></tr>
<tr><td><b>Pre-commit</b></td><td>Ruff, ruff-format, and type-check hooks (opt-in)</td><td><img src="https://img.shields.io/badge/-optional-blue" alt="Optional" width="64"></td></tr>
<tr><td><b>Continuous Deploy</b></td><td>Generates a dedicated SSH deploy key, installs it on your server, pushes secrets to GitHub, and scaffolds a deploy workflow (manual trigger by default)</td><td><img src="https://img.shields.io/badge/-optional-blue" alt="Optional" width="64"></td></tr>
</tbody>
</table>

## Deploying Your Stack

| Capability | What you get | |
|---|---|---|
| **[Deploy CLI](https://docs.aegis-stack.io/deployment/)** | One-command deploys to any VPS over SSH (rsync + Docker), no PaaS lock-in | ![Available](https://img.shields.io/badge/-available-2ea043) |
| **[Server Setup](https://docs.aegis-stack.io/deployment/#aegis-deploy-setup)** | `aegis deploy-setup` provisions Ubuntu, Debian, or Fedora boxes (Docker + firewall) | ![Available](https://img.shields.io/badge/-available-2ea043) |
| **[Backups & Rollback](https://docs.aegis-stack.io/deployment/#backup-and-rollback)** | `pg_dump` before every deploy, retention policy, automatic rollback on failed health checks | ![Available](https://img.shields.io/badge/-available-2ea043) |
| **[TLS / HTTPS](https://docs.aegis-stack.io/deployment/#tlshttps-with-lets-encrypt)** | Let's Encrypt via the Traefik ingress component, zero config when a domain is set | ![Optional](https://img.shields.io/badge/-optional-blue) |

[Deployment Docs →](https://docs.aegis-stack.io/deployment/)

## Your Stack Grows With You

**Your choices aren't permanent.** Start with what you need today, add when requirements change, remove what you outgrow.

```bash
# Monday: Ship MVP
aegis init my-api

# Week 3: Add scheduled reports
aegis add scheduler --project-path ./my-api

# Month 2: Need async workers
aegis add worker --project-path ./my-api

# Month 6: Scheduler not needed
aegis remove scheduler --project-path ./my-api

# Stay current with template improvements
aegis update
```

| Starter | Add Later? | Remove Later? | Git Conflicts? |
|-----------|------------|---------------|----------------|
| **Others** | Locked at init | Manual deletion | High risk |
| **Aegis Stack** | One command | One command | Auto-handled |

<img src="docs/images/aegis-evolution-demo.gif" alt="Component Evolution Demo" width="480">

Most starters lock you in at `init`. Aegis Stack doesn't. See **[Evolving Your Stack](https://docs.aegis-stack.io/evolving-your-stack/)** for the complete guide.

## Overseer - Your Application's Control Plane

<img src="docs/images/overseer-demo.gif" alt="Overseer" width="480">

<sub>[Live Demo: sector-7g.dev/dashboard](https://sector-7g.dev/dashboard/)</sub>

**[Overseer](https://docs.aegis-stack.io/overseer/)** is the embedded control plane that ships with every Aegis Stack project.

- Live health of every component and service in one view
- Worker queues, scheduled jobs, recent runs
- Database schema, tables, and migration state
- AI token usage and conversation history
- Auth sessions and user activity
- No external tooling, no vendor integrations, no setup

## CLI - First-Class System Interface

<img src="docs/images/cli-demo.gif" alt="CLI Demo" width="480">

The Aegis CLI is a first-class interface to your running system. Not just a health check, but a full inspection layer.

- Component-aware commands for every running subsystem
- Inspect worker queues, scheduler runs, database state
- Query AI usage, auth sessions, service configuration
- Same data Overseer sees, terminal-native
- Built into every generated project, no extra installs

## Illiana - Optional System Operator

<img src="docs/images/illiana-demo.gif" alt="Illiana Demo" width="480">

When the AI service is enabled, Aegis exposes an additional interface: **Illiana**, a conversational operator over your running system.

- Ask questions in plain language about live system state
- Backed by live telemetry from Overseer and the CLI
- Optional RAG over your codebase for code-aware answers
- Opt-in: only available when the AI service is on
- Nothing in the stack depends on her being there

## Powered By Aegis Stack

- **[Aegis Pulse](https://pulse.aegis-stack.io/)** - Package analytics with honest decomposition (Total / Filtered / Human)
- **[Sector 7G](https://sector-7g.dev/dashboard/)** - Live demo: millions of tasks on a single $5 VPS, zero restarts
- **[NWVault Revival](https://167.99.48.44/)** - Searchable archive of the original Neverwinter Vault (2002-2014), built in 24 hours

## Learn More

- **[Overseer](https://docs.aegis-stack.io/overseer/)** - Built-in system dashboard
- **[Deployment](https://docs.aegis-stack.io/deployment/)** - Deploy with backups, rollback, and health checks
- **[CLI Reference](https://docs.aegis-stack.io/cli-reference/)** - Complete command reference
- **[Evolving Your Stack](https://docs.aegis-stack.io/evolving-your-stack/)** - Add/remove components as needs change
- **[Technology Stack](https://docs.aegis-stack.io/technology/)** - Battle-tested technology choices
- **[About](https://docs.aegis-stack.io/about/)** - The philosophy and vision behind Aegis Stack

## For The Veterans

<img src="docs/images/ron-swanson.gif" alt="Ron Swanson" width="480">

No reinventing the wheel. Just the tools you already know, pre-configured and ready to compose.

Aegis Stack respects your expertise. No custom abstractions or proprietary patterns to learn. Pick your components, get a production-ready foundation, and build your way.

Aegis gets out of your way so you can get started.
