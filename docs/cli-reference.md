# CLI Reference

Complete reference for the Aegis Stack command-line interface.

## aegis init

Create a new Aegis Stack project with your chosen components.

**Usage:**
```bash
aegis init PROJECT_NAME [OPTIONS]
```

**Arguments:**

- `PROJECT_NAME` - Name of the new project to create (required)

**Options:**

- `--components, -c TEXT` - Comma-separated list of components (scheduler,database,cache)
- `--interactive / --no-interactive, -i / -ni` - Use interactive component selection (default: interactive)
- `--force, -f` - Overwrite existing directory if it exists
- `--output-dir, -o PATH` - Directory to create the project in (default: current directory) 
- `--yes, -y` - Skip confirmation prompt

**Examples:**
```bash
# Simple API project
aegis init my-api

# Background processing system
aegis init task-processor --components scheduler

# Full stack (future)
aegis init webapp --components scheduler,database,cache

# Non-interactive with custom location
aegis init my-app --components scheduler --no-interactive --output-dir /projects --yes
```

**Available Components:**

| Component | Status | Description |
|-----------|--------|-------------|
| `scheduler` | ✅ Available | APScheduler-based async task scheduling |
| `database` | 🚧 Coming Soon | SQLAlchemy + asyncpg for PostgreSQL |
| `cache` | 🚧 Coming Soon | Redis-based async caching |


## aegis version

Show the Aegis Stack CLI version.

**Usage:**
```bash
aegis version
```

**Example Output:**
```
Aegis Stack CLI v1.0.0
```

## Global Options

**Help:**
```bash
aegis --help          # Show general help
aegis COMMAND --help  # Show help for specific command
```

## Exit Codes

- `0` - Success
- `1` - Error (invalid arguments, project creation failed, etc.)

## Environment

The CLI respects these environment variables:

- Standard Python environment variables
- UV environment variables (for dependency management)

## Project Structure

Projects created with `aegis init` follow this structure:

```
my-project/
├── app/
│   ├── components/
│   │   ├── backend/        # FastAPI backend
│   │   ├── frontend/       # Flet frontend  
│   │   └── scheduler.py    # APScheduler (if included)
│   ├── core/              # Framework utilities
│   ├── services/          # Business logic
│   └── integrations/      # App composition
├── tests/                 # Test suite
├── docs/                  # Documentation
├── pyproject.toml         # Project configuration
├── Dockerfile             # Container definition
├── docker-compose.yml     # Multi-service orchestration
├── Makefile              # Development commands
└── .env.example          # Environment template
```

## Development Workflow

After creating a project:

```bash
cd my-project
uv sync                    # Install dependencies and create virtual environment
source .venv/bin/activate  # Activate virtual environment (important!)
cp .env.example .env       # Configure environment
make run-local             # Start development server
make test                  # Run test suite
make check                 # Run all quality checks
```