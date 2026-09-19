# Installation Guide

Aegis Stack can be used in multiple ways depending on your needs and preferences.

## System Requirements

Before installing Aegis Stack, ensure you have the following:

### Required

- **Python 3.11 or higher** - Core runtime for Aegis Stack and generated projects
- **Docker & Docker Compose** - Required for generated projects' development workflow

### Why Docker?

Generated projects use Docker for:

- **Consistent development environments** - Same setup across all machines
- **Service dependencies** - Redis for worker component, health monitoring infrastructure
- **Standard workflow** - The `make serve` command uses `docker compose` under the hood
- **Production parity** - Development closely mirrors production deployment

!!! note "Docker Alternatives"
    While the standard workflow uses Docker, generated projects are standard Python applications. Advanced users can manually run components (the [ASGI server](components/backend/serving.md) for the backend, direct Redis installation, etc.), but this workflow is currently undocumented and unsupported.

!!! note "Windows"
    `make` isn't a native Windows binary. After installing the project's dev dependencies once (`uv sync --all-extras`), every `make <target>` command in a generated project also works as `uv run poe <target>` (for example `uv run poe serve`), including the standard Docker-based workflow above. Run `uv run poe -h` for the full list.

### Installing Docker

- **macOS/Windows**: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux**: [Docker Engine](https://docs.docker.com/engine/install/) + [Docker Compose](https://docs.docker.com/compose/install/)

## Installation

Choose the method that works best for your workflow:

=== "uvx (Recommended)"

    `uvx` ships with [uv](https://docs.astral.sh/uv/getting-started/installation/) (Astral's Python package manager) and runs a tool in a temporary, isolated environment without installing it first. If you don't have uv yet, install it once and `uvx` becomes available automatically.

    The fastest way to use Aegis Stack without any installation:

    ```bash
    # Create a new project
    uvx aegis-stack init my-project

    # Get help
    uvx aegis-stack --help

    # Create with specific components
    uvx aegis-stack init my-api --components worker,scheduler
    ```

    **Benefits:**

    - No installation required
    - Uses the latest version on first run, then a fast cached copy (run `uvx aegis-stack@latest` to refresh)
    - Zero setup, works immediately
    - Isolated execution environment
    - Perfect for trying Aegis Stack or one-off usage

    **Best for:** Quick start, experimentation, CI/CD, one-off usage

=== "uv tool"

    Saw uvx above? `uvx` runs Aegis Stack without installing it; `uv tool install` installs it permanently so you can just type `aegis`.

    Install Aegis Stack as a persistent CLI tool with uv:

    ```bash
    # Install persistently
    uv tool install aegis-stack

    # Use the installed version
    aegis init my-project
    aegis --help
    aegis components
    ```

    **Benefits:**

    - Fastest subsequent runs (pre-installed)
    - Simple `aegis` command
    - Easy to upgrade with `uv tool upgrade aegis-stack`
    - Persistent installation

    **Best for:** Daily development work, regular CLI usage

=== "pip"

    Install Aegis Stack with pip:

    ```bash
    # Install from PyPI
    pip install aegis-stack

    # Use the installed version
    aegis init my-project
    aegis --help
    aegis components
    ```

    **Benefits:**

    - Works in any Python environment
    - Familiar to all Python developers
    - Compatible with existing workflows

    **Best for:** Traditional workflows, existing pip-based setups

=== "Development"

    For contributing, customizing, or working with the latest development version:

    ```bash
    # Clone the repository
    git clone https://github.com/lbedner/aegis-stack
    cd aegis-stack

    # Install with all development dependencies
    uv sync --all-extras

    # Use development version
    .venv/bin/aegis init my-project

    # Run tests
    .venv/bin/pytest

    # Build documentation
    .venv/bin/mkdocs serve
    ```

    **Benefits:**

    - Latest unreleased features
    - Full development environment
    - Ability to modify and test changes
    - Access to development tools

    **Best for:** Contributing, customizing, latest features

## CLI Language Support

The Aegis Stack CLI is fully localized in 9 languages. Set your language with a flag or an environment variable:

```bash
# Via flag
aegis --lang fr init my-project

# Via environment variable
export AEGIS_LANG=fr
aegis init my-project
```

Supported languages:

| Code | Language |
| --- | --- |
| `en` | English (default) |
| `de` | Deutsch |
| `es` | Español |
| `fr` | Français |
| `ja` | 日本語 |
| `ko` | 한국어 |
| `ru` | Русский |
| `zh` | 简体中文 (Simplified Chinese) |
| `zh_Hant` | 繁體中文 (Traditional Chinese) |

If you don't set a language, Aegis Stack detects it from your system locale and falls back to English.
