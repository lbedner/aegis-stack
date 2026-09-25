<img src="images/aegis-manifesto.png#only-light" alt="Aegis Stack" width="400">
<img src="images/aegis-manifesto-dark.png#only-dark" alt="Aegis Stack" width="400">

**Build production-ready Python applications with your chosen components and services.**

[![GitHub Stars](https://img.shields.io/github/stars/lbedner/aegis-stack)](https://github.com/lbedner/aegis-stack)
[![CI](https://github.com/lbedner/aegis-stack/workflows/CI/badge.svg)](https://github.com/lbedner/aegis-stack/actions/workflows/ci.yml)
[![Documentation](https://github.com/lbedner/aegis-stack/workflows/Deploy%20Documentation/badge.svg)](https://github.com/lbedner/aegis-stack/actions/workflows/docs.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

Aegis Stack is a CLI that scaffolds modular Python applications. Select exactly the components you need - no bloat, no unused dependencies.

## Quick Start

```bash
# Run instantly without installation
# (opens a full-screen guided setup; add --quick for one-line prompts)
uvx aegis-stack init my-api

# Create with user authentication
uvx aegis-stack init user-app --services auth

# Create with background processing
uvx aegis-stack init task-processor --components scheduler,worker

# Start building
cd my-api && uv sync && cp .env.example .env && make serve
```

## Installation

**No installation needed** - just run it:

```bash
uvx aegis-stack init my-project
```

That's it. [`uvx`](https://docs.astral.sh/uv/) downloads, installs, and runs Aegis Stack in one command.

---

**Alternative methods:** [Installation Guide](installation.md) covers `uv tool install` and `pip install` for specific workflows.

## 🌱 Your Stack Grows With You

**Your choices aren't permanent.** Start with what you need today, add components when requirements change, remove what you outgrow.

```bash
# Monday: Ship MVP
aegis init my-api

# Week 3: Add scheduled reports
aegis add scheduler --project-path ./my-api

# Month 2: Need async workers
aegis add worker --project-path ./my-api

# Month 6: Scheduler not needed
aegis remove scheduler --project-path ./my-api
```

| Starter | Add Later? | Remove Later? | Git Conflicts? |
|-----------|------------|---------------|----------------|
| **Others** | ❌ Locked at init | ❌ Manual deletion | ⚠️ High risk |
| **Aegis Stack** | ✅ One command | ✅ One command | ✅ Merged, conflicts marked for review |

Most starters lock you in at `init`. Aegis Stack doesn't. See **[Evolving Your Stack](evolving-your-stack.md)** for the complete guide.

## Available Components & Services

### Infrastructure Components
| Component | Purpose | Status |
|-----------|---------|--------|
| **Core** (FastAPI + Flet) | Web API + Overseer | ✅ **Always Included** |
| **[Web Frontend](components/web-frontend/index.md)** (htmx) | Server-rendered pages at `/`, beside the Overseer | ✅ **Available** |
| **Database** | SQLite or PostgreSQL + SQLModel ORM | ✅ **Available** |
| **Scheduler** | Background tasks, cron jobs | ✅ **Available** |
| **Worker** | Task queues (arq, Dramatiq, or TaskIQ) | ✅ **Available** |
| **Observability** | Tracing, metrics, logging (Logfire) | ✅ **Available** |
| **Cache** | Redis caching and sessions | 🚧 **Coming Soon** |

### Business Services
| Service | Purpose | Status |
|---------|---------|--------|
| **[AI](services/ai/index.md)** | Multi-provider AI chat | 🧪 **Experimental** |
| **[Auth](services/auth/index.md)** | User authentication & JWT | ✅ **Available** |
| **[Blog](services/blog/index.md)** | Markdown publishing, tags, drafts | 🧪 **Experimental** |
| **[Comms](services/comms/index.md)** | Email, SMS, voice calls | 🧪 **Experimental** |
| **[Insights](services/insights/index.md)** | Adoption metrics (GitHub, PyPI, Plausible, Reddit) | 🧪 **Experimental** |
| **[Payment](services/payment/index.md)** | Stripe checkout, subscriptions, refunds, disputes | 🧪 **Experimental** |

## See It In Action

### System Health Dashboard

![System Health Dashboard](images/dashboard-light.png#only-light)
![System Health Dashboard](images/dashboard-dark.png#only-dark)

Real-time monitoring with component status, health percentages, and cross-platform deployment (web, desktop, mobile).

### CLI Health Monitoring

![CLI Health Check](images/cli_health_check.png)

Rich terminal output showing detailed component status, health metrics, and system diagnostics.

## Learn More

- **[CLI Reference](cli-reference.md)** - Complete command reference
- **[Components](components/index.md)** - Deep dive into available components
- **[Services](services/index.md)** - Business services (auth, AI)
- **[About](about.md)** - The philosophy and vision behind Aegis Stack
- **[Evolving Your Stack](evolving-your-stack.md)** - Add/remove components as needs change
- **[Technology Stack](technology.md)** - Battle-tested technology choices

## For The Veterans

![Ron Swanson](images/ron-swanson.gif)

No reinventing the wheel. Just the tools you already know, pre-configured and ready to compose.

Aegis Stack respects your expertise. We maintain existing standards - FastAPI for APIs, SQLModel for databases, arq for workers. No custom abstractions or proprietary patterns to learn. Pick your components, get a production-ready foundation, and build your way.

The tool gets out of your way so you can get started.
