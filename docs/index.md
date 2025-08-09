# Aegis Stack 🛡️

[![CI](https://github.com/lbedner/aegis-stack/workflows/CI/badge.svg)](https://github.com/lbedner/aegis-stack/actions/workflows/ci.yml)
[![Documentation](https://github.com/lbedner/aegis-stack/workflows/Deploy%20Documentation/badge.svg)](https://github.com/lbedner/aegis-stack/actions/workflows/docs.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**Build production-ready Python applications with your chosen components.**

Aegis Stack is a CLI-driven framework for creating custom Python applications. Select exactly the components you need - no bloat, no unused dependencies.

## 🚀 Quick Start

```bash
# Install
pip install aegis-stack

# Create a simple API
aegis init my-api

# Create with background processing  
aegis init task-processor --components scheduler

# Start building
cd my-project && uv sync && source .venv/bin/activate && make run-local
```

## 🧩 Available Components

| Component | Purpose | Status |
|-----------|---------|--------|
| **Core** (FastAPI + Flet) | Web API + Frontend | ✅ **Included** |
| **Scheduler** | Background tasks, cron jobs | ✅ **Available** |
| **Database** | PostgreSQL + SQLAlchemy + Alembic | 🚧 **Coming Soon** |
| **Cache** | Redis caching and sessions | 🚧 **Coming Soon** |

## What You Get

- **FastAPI backend** with automatic API documentation
- **Flet frontend** with system health dashboard  
- **CLI management** with health monitoring commands
- **Production ready** with structured logging and containerization
- **Async-first** architecture for high-concurrency workloads

## 📱 System Health Dashboard

![System Health Dashboard](images/dashboard.png)

Real-time monitoring with component status, health percentages, and cross-platform deployment (web, desktop, mobile).

## 📚 Learn More

- **[📖 CLI Reference](cli-reference.md)** - Complete command reference
- **[🏗️ Components](components/index.md)** - Deep dive into available components  
- **[🧠 Philosophy](philosophy.md)** - Architecture and design principles

## Development Commands

```bash
make run-local    # Start development server
make test         # Run test suite  
make check        # Run all quality checks
make docs-serve   # Serve documentation
```

Built on FastAPI, Flet, Typer, and other open-source tools.