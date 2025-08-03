# Aegis Stack 🛡️

**A production-ready, async-first Python foundation for builders who refuse to wait.**

Aegis Stack provides a minimal, yet powerful, set of tools and patterns to help you build and deploy robust, scalable applications quickly. It's designed for developers who think in systems, not scripts, and who value speed, simplicity, and scalability.

---

## Core Features

- **Full-Stack Python:** A unified development experience with [FastAPI](https://fastapi.tiangolo.com/) for the backend and [Flet](https://flet.dev/) for the frontend.
- **Async-First Architecture:** Built from the ground up with `asyncio` to handle high-concurrency workloads efficiently.
- **Composable Lifecycle Management:** A powerful, registry-based system for managing startup and shutdown events.
- **Automatic Service Discovery:** A "drop-in" architecture where services are automatically discovered and integrated, no manual configuration required.
- **Structured, Production-Ready Logging:** Out-of-the-box structured logging with `structlog`, providing human-readable logs for development and JSON logs for production.
- **Modern Documentation:** A beautiful, maintainable documentation site powered by [MkDocs](https://www.mkdocs.org/) and the [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) theme.

## Philosophy

Aegis Stack is built on three pillars:

1.  **Speed:** Get from idea to production as quickly as possible.
2.  **Simplicity:** Favor clear, Pythonic patterns over complex, magical frameworks.
3.  **Scalability:** Start with a simple monolith and evolve into a distributed system as your needs grow.

To learn more, check out the full [**Documentation**](https://aegis-stack.github.io/aegis-stack/). (Note: This link will be valid once deployed via GitHub Pages).

## Usage

This project uses a `Makefile` to provide convenient commands for common tasks.

### Running the Application

To run the local development server with live reloading:
```bash
make run-local
```
The application will be available at `http://127.0.0.1:8000`.

### Documentation

To serve the documentation locally with live reloading:
```bash
make docs-serve
```
The documentation will be available at `http://127.0.0.1:8001`.

### Code Quality and Tests

To run all checks (linting, type checking, and tests) at once:
```bash
make check
```
