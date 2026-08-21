# CLI Reference

Complete reference for the Aegis Stack command-line interface.

## Global Options

These options work with all commands and must be specified **before** the command name.

**Usage:**
```bash
aegis [GLOBAL OPTIONS] COMMAND [COMMAND OPTIONS]
```

**Available Options:**

- `--verbose, -v` - Enable verbose output (show detailed file operations)
- `--help` - Show help message

**Examples:**
```bash
# Correct: Global flag before command
aegis --verbose init my-project
aegis --verbose add scheduler
aegis -v remove worker

# Incorrect: Global flag after command (will fail)
aegis init my-project --verbose  ❌
```

**What --verbose Shows:**
- Detailed file operation logs
- Template rendering details
- Component resolution steps
- Dependency installation progress

---

## Quick Start Commands

### aegis version

Show the Aegis Stack CLI version.

**Usage:**
```bash
aegis version
```

**Example Output:**
```
Aegis Stack CLI v0.2.1
```

### aegis components

List available components with their status and dependencies.

**Usage:**
```bash
aegis components
```

**Example Output:**
```
CORE COMPONENTS
========================================
  backend      - FastAPI backend server (always included)
  frontend     - Flet frontend interface (always included)

INFRASTRUCTURE COMPONENTS
========================================
  worker       - Background task processing (arq, Dramatiq, or TaskIQ)
               Requires: redis
  scheduler    - Scheduled task execution infrastructure
  database     - Database with SQLModel ORM (SQLite or PostgreSQL)
  redis        - Redis cache and message broker
  ingress      - Traefik reverse proxy and load balancer
               Recommends: backend
  observability - Logfire observability, tracing, and metrics

FRONTEND COMPONENTS
========================================
  htmx         - Server-rendered htmx web frontend
```

### aegis services

List available services with their required components.

**Usage:**
```bash
aegis services
```

**Example Output:**
```
AVAILABLE SERVICES
========================================

Authentication Services
----------------------------------------
  auth         - User authentication and authorization with JWT tokens
               Requires components: backend, database

AI & Machine Learning Services
----------------------------------------
  ai           - AI chatbot with PydanticAI engine
               Requires components: backend
               Supports: OpenAI, Anthropic, Google, Groq, Mistral, Cohere
```

### aegis blueprints

List available blueprints: preset component and service selections you can start a project from.

**Usage:**
```bash
aegis blueprints
```

**Example Output:**
```
AVAILABLE BLUEPRINTS
========================================

  finance  Personal finance
      Track accounts, budgets, and goals, with a local AI analyst that narrates what changed.
      Includes: worker, scheduler, database, ai, finance

Start a project from one:
   aegis init my-app --blueprint <name>
```

A blueprint only pre-fills the answers `aegis init` would ask for, so the stack it produces is identical to selecting those options by hand. Add whatever it leaves out afterwards with `aegis add` and `aegis add-service`.

---

## Project Management Commands

### aegis init

Create a new Aegis Stack project with your chosen components and services.

**Usage:**
```bash
aegis init PROJECT_NAME [OPTIONS]
```

**Arguments:**

- `PROJECT_NAME` - Name of the new project to create (required)

**Options:**

- `--components, -c TEXT` - Comma-separated list of components
- `--services, -s TEXT` - Comma-separated list of services
- `--blueprint, -b TEXT` - Start from a named blueprint, a preset component and service selection (see `aegis blueprints`). Interactively this opens the guided review with the stack already resolved; with `--no-interactive` it expands directly. Explicit `--components`/`--services` win where given.
- `--interactive / --no-interactive, -i / -ni` - Use interactive selection (default: interactive)
- `--guided / --quick` - Interactive style: the full-screen guided setup (default) or the classic one-line prompts (`--quick`). Guided needs a real terminal of at least 60x20; anything else falls back to quick prompts automatically.
- `--force, -f` - Overwrite existing directory if it exists
- `--output-dir, -o PATH` - Directory to create the project in (default: current directory)
- `--yes, -y` - Skip confirmation prompt

**Examples:**
```bash
# Simple API project (full-screen guided setup)
aegis init my-api

# Personal finance stack from the blueprint
aegis init money --blueprint finance

# Classic one-line prompts instead
aegis init my-api --quick

# Background processing with scheduler
aegis init task-processor --components scheduler

# User authentication system
aegis init user-app --services auth --components database

# AI chatbot application
aegis init chatbot --services ai

# Full stack with auth and AI
aegis init full-app --services auth,ai --components database,scheduler

# Non-interactive with custom location
aegis init my-app --services auth --components database --no-interactive --output-dir /projects --yes
```

**The guided setup:**

![The guided setup: the Worker component screen with the selections sidebar](images/guided-setup.png)

Running `aegis init my-app` in a normal terminal opens a full-screen guided setup: one page per component and service, each with a short explanation, its hard requirements, what it pairs well with, and a link to its documentation page. A sidebar tracks your selections as you go.

The flow is welcome page, a starting-point screen (blank canvas, or pick from the blueprint gallery), the preselected foundation (backend + frontend), one question per building block, a review screen showing the resolved plan (with file and dependency detail panes), then the build itself with live progress and a closing summary that includes a copyable one-liner to recreate the same stack anywhere.

**Blueprints:**

A blueprint is a ready-made stack. Choosing one on the starting-point screen opens the gallery, where each entry shows what it contains; picking it answers every question for you (components, services, and the value decisions, journaled just like keypresses) and takes you straight to the review screen with the whole resolved plan. One `enter` builds it. The pages that orient someone assembling a stack by hand, the foundation summary and the selections sidebar, are skipped: there are no answers of your own to keep track of.

Blueprints are starting points, not locked paths. Anything a blueprint leaves out is added afterwards with `aegis add` and `aegis add-service`, which is the same way every project grows. `esc` on the review undoes the one decision you actually made and returns you to the starting point, so you can choose a different blueprint or take the blank canvas and answer the questions yourself.

Run `aegis blueprints` to see the roster, or name one directly with `aegis init my-app --blueprint finance`.

Keys:

- `←/→` move, `enter` select
- `esc` go back one question (your previous answer is re-asked; every downstream effect is recomputed)
- `s` skip the remaining component questions and jump to services
- `f` finish: keep what you have picked so far and go straight to review
- `q` quit
- On the review screen: `f` shows the files to be created, `d` the dependencies, `enter` builds
- On checklist screens (AI providers): `enter`/`space` toggle an entry, pick `Continue` to move on

Selections follow the same rules as every other mode: accepting worker pulls in redis (and skips the redis question), a persistent scheduler backend or AI conversation storage brings the database with it, and one database engine serves the whole project.

The guided setup needs a real terminal of at least 60x20. Pipes, CI, and small terminals fall back to the classic prompts automatically, and `--quick` forces them.

**Service Auto-Resolution:**

When you select services, required components are automatically added:

- `--services auth` → Auto-adds `database` component
- `--services blog` → Auto-adds `database` component
- `--services ai` → No additional components (backend always included)
- `--services comms` → No additional components (backend always included)
- Backend and frontend components are **always included** in every project

**Component Dependencies:**

Some components require others and will be auto-added:

- `worker` → Auto-adds `redis`
- `scheduler[sqlite]` → Auto-adds `database`

**Examples with Auto-Resolution:**
```bash
# Auth service auto-adds database
aegis init user-app --services auth
# Result: backend + frontend + database + auth service

# Worker auto-adds redis
aegis init task-app --components worker
# Result: backend + frontend + redis + worker

# Scheduler with SQLite auto-adds database
aegis init cron-app --components "scheduler[sqlite]"
# Result: backend + frontend + database + scheduler
```

---

### aegis add

Add components to an existing Aegis Stack project.

**Usage:**
```bash
aegis add COMPONENTS [OPTIONS]
```

**Arguments:**

- `COMPONENTS` - Comma-separated list of components to add

**Options:**

- `--backend, -b TEXT` - Scheduler backend: 'memory' (default) or 'sqlite' (enables persistence)
- `--interactive, -i` - Use interactive component selection
- `--project-path, -p PATH` - Path to the Aegis Stack project (default: current directory)
- `--yes, -y` - Skip confirmation prompt

**Examples:**
```bash
# Add scheduler with memory backend
aegis add scheduler

# Add scheduler with SQLite persistence
aegis add scheduler --backend sqlite
# or using bracket syntax
aegis add "scheduler[sqlite]"

# Add worker (auto-includes redis)
aegis add worker

# Add the htmx web frontend (server-rendered pages at /)
aegis add htmx

# Add multiple components
aegis add database,scheduler

# Add to specific project
aegis add scheduler --project-path ../my-project

# Interactive mode
aegis add --interactive
```

**How It Works:**

1. Validates project was generated with Copier
2. Checks component dependencies (auto-adds required components)
3. Renders component templates with Jinja2
4. Copies files to project (skips existing files)
5. Updates `.copier-answers.yml` with new configuration
6. Regenerates shared files (docker-compose.yml, pyproject.toml)
7. Runs `uv sync` to install new dependencies
8. Runs `make fix` to format code

**Notes:**

- Components added incrementally without breaking existing code
- Shared files automatically regenerated with backups
- Changes are non-destructive (commit before running for easy rollback)
- Use `--verbose` flag to see detailed operation logs

---

### aegis add-service

Add services to an existing Aegis Stack project.

**Usage:**
```bash
aegis add-service SERVICES [OPTIONS]
```

**Arguments:**

- `SERVICES` - Comma-separated list of services to add

**Options:**

- `--interactive, -i` - Use interactive service selection
- `--project-path, -p PATH` - Path to the Aegis Stack project (default: current directory)
- `--yes, -y` - Skip confirmation prompt

**Examples:**
```bash
# Add auth service (auto-adds database if not present)
aegis add-service auth

# Add AI service
aegis add-service ai

# Add multiple services
aegis add-service auth,ai

# Interactive service selection
aegis add-service --interactive

# Non-interactive with auto-yes
aegis add-service auth --yes --project-path ../my-project
```

**Service Auto-Resolution:**

Services automatically add their required components if missing:

- `auth` → Requires `database` component (auto-added if missing)
- `ai` → Requires `backend` component (always present)

**Post-Addition Setup:**

After adding services, follow these steps:

**For Auth Service:**
```bash
make migrate                       # Apply auth database migrations
my-project auth create-test-users  # Create test users for development
my-project auth list-users         # Verify users created
```

**For AI Service:**

Configure provider in `.env`:
```env
AI_PROVIDER=public  # Options: public, openai, anthropic, google, groq, mistral, cohere

# For paid providers, add API key:
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
```

Test the AI service:
```bash
my-project ai status               # Check configuration
my-project ai chat                 # Start interactive chat
my-project ai providers            # See all available providers
```

**Important Notes:**

- Only works with Copier-generated projects (default since v0.2.0)
- Requires git repository (for change tracking)
- Services require their dependencies - they will be auto-added
- Review changes with `git diff` before committing

See **Generated Project CLI** section below for full command reference.

---

### aegis remove

Remove components from an existing Aegis Stack project.

**Usage:**
```bash
aegis remove COMPONENTS [OPTIONS]
```

**Arguments:**

- `COMPONENTS` - Comma-separated list of components to remove

**Options:**

- `--interactive, -i` - Use interactive component selection
- `--project-path, -p PATH` - Path to the Aegis Stack project (default: current directory)
- `--yes, -y` - Skip confirmation prompt

**Examples:**
```bash
# Remove scheduler component
aegis remove scheduler

# Remove multiple components
aegis remove scheduler,worker

# Interactive mode
aegis remove --interactive
```

**How It Works:**

1. Validates project was generated with Copier
2. Checks component is currently enabled
3. Deletes component files and directories
4. Cleans up empty parent directories
5. Updates `.copier-answers.yml` to disable component
6. Regenerates shared files (docker-compose.yml, pyproject.toml)
7. Runs `uv sync` to clean up unused dependencies
8. Runs `make fix` to format code

**Important Warnings:**

- **THIS OPERATION DELETES FILES** - Commit your changes to git first
- Core components (backend, frontend) cannot be removed
- Removing scheduler with SQLite persistence leaves `data/scheduler.db` intact
- Shared template files are regenerated (backups created automatically)
- Redis is auto-removed when worker is removed (no standalone functionality)

---

### aegis update

Update an existing Copier-based project to the latest template version.

**Usage:**
```bash
aegis update [OPTIONS]
```

**Options:**

- `--project-path PATH` - Path to project to update (default: current directory)
- `--to-version TEXT` - Update to specific template version (default: latest)
- `--force, -f` - Accept all template changes automatically
- `--yes, -y` - Skip confirmation prompt
- `--dry-run` - Preview changes without applying them

**Examples:**
```bash
# Update current project to latest template
aegis update

# Update specific project
aegis update --project-path ../my-project

# Update to specific template version
aegis update --to-version 0.2.0

# Preview changes without applying
aegis update --dry-run

# Auto-accept all updates
aegis update --force --yes
```

**How It Works:**

1. Validates project was generated with Copier
2. Checks current template version from `.copier-answers.yml`
3. Fetches latest template version (or specified version)
4. Compares current files with template updates
5. Shows diff of changes to be applied
6. Prompts for conflict resolution
7. Applies updates and creates backup files
8. Runs `uv sync` to update dependencies
9. Runs `make fix` to format updated code

**What Gets Updated:**

- ✅ Template infrastructure files
- ✅ Shared files (docker-compose.yml, pyproject.toml, Makefile)
- ✅ Component implementations (if unmodified)
- ✅ Test infrastructure
- ✅ Documentation templates

**What's Preserved:**

- ✅ Your custom business logic
- ✅ Your environment variables (.env)
- ✅ Your database migrations
- ✅ Your custom models and services
- ✅ Files you've modified (marked as conflicts)

**Important Notes:**

- **Always commit before updating**: `git add . && git commit -m "Pre-update checkpoint"`
- **Test after updating**: Run `make check` to verify everything works
- Use `--dry-run` first to preview changes

---

## Deployment Commands

Commands for deploying your project to a remote server. See the **[Deployment Guide](deployment/index.md)** for full workflows and examples.

### aegis deploy-init

Initialize deployment configuration for a project.

**Usage:**
```bash
aegis deploy-init [OPTIONS]
```

**Options:**

- `--host, -h TEXT`, Server IP address or hostname
- `--user, -u TEXT`, SSH user for deployment (default: `root`)
- `--path, -p TEXT`, Deployment path on server (default: `/opt/{project-name}`)
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-init --host 192.168.1.100
aegis deploy-init --host myserver.com --user deploy
```

---

### aegis deploy-setup

Provision a remote server for deployment. Installs Docker, configures firewall, and prepares the server.

**Usage:**
```bash
aegis deploy-setup [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-setup
```

---

### aegis deploy

Deploy the project to the configured server. Creates a backup, syncs files, builds Docker images, starts services, and runs a health check. Auto-rollback on failure.

**Usage:**
```bash
aegis deploy [OPTIONS]
```

**Options:**

- `--build / --no-build`, Build images before deploying (default: `--build`)
- `--backup / --no-backup`, Create backup before deploying (default: `--backup`)
- `--health-check / --no-health-check`, Run health check after deploying (default: `--health-check`)
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy
aegis deploy --no-build
aegis deploy --no-backup --no-health-check
```

---

### aegis deploy-backup

Create a backup of the currently deployed application on the remote server.

**Usage:**
```bash
aegis deploy-backup [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-backup
```

---

### aegis deploy-backups

List available deployment backups with timestamps, sizes, and database dump status.

**Usage:**
```bash
aegis deploy-backups [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-backups
```

---

### aegis deploy-rollback

Rollback to a previous deployment backup. Uses the latest backup if none specified.

**Usage:**
```bash
aegis deploy-rollback [OPTIONS]
```

**Options:**

- `--backup, -b TEXT`, Backup timestamp to rollback to (default: latest)
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-rollback
aegis deploy-rollback --backup 2026-03-11_183045
```

---

### aegis deploy-logs

View logs from the deployed application.

**Usage:**
```bash
aegis deploy-logs [OPTIONS]
```

**Options:**

- `--follow / --no-follow, -f`, Follow log output (default: `--follow`)
- `--service, -s TEXT`, Show logs for a specific service
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-logs
aegis deploy-logs --no-follow
aegis deploy-logs --service webserver
```

---

### aegis deploy-status

Check the status of deployed services.

**Usage:**
```bash
aegis deploy-status [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-status
```

---

### aegis deploy-stop

Stop all deployed services.

**Usage:**
```bash
aegis deploy-stop [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-stop
```

---

### aegis deploy-restart

Restart all deployed services.

**Usage:**
```bash
aegis deploy-restart [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-restart
```

---

### aegis deploy-shell

Open a shell in a deployed container.

**Usage:**
```bash
aegis deploy-shell [OPTIONS]
```

**Options:**

- `--service, -s TEXT`, Service to connect to (default: `webserver`)
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-shell
aegis deploy-shell --service redis
```

---

### aegis ingress-enable

Enable TLS (HTTPS) on a project with the ingress component. Configures Let's Encrypt certificates via Traefik.

**Usage:**
```bash
aegis ingress-enable [OPTIONS]
```

**Options:**

- `--domain, -d TEXT`, Domain name for TLS certificate (e.g., `example.com`)
- `--email, -e TEXT`, Email for Let's Encrypt certificate notifications
- `--project-path, -p TEXT`, Path to the project (default: current directory)
- `--yes, -y`, Skip confirmation prompts

**Examples:**
```bash
aegis ingress-enable --domain example.com --email admin@example.com
aegis ingress-enable -d example.com -e admin@example.com -y
aegis ingress-enable  # interactive prompts
```

---

## Generated Project CLI

When you add services to a project, they install their own CLI commands as entry point scripts. These commands are available after running `uv sync` in your generated project.

**Script Installation:**

All generated projects get a CLI script matching the project name:
```bash
# If project is named "my-app"
my-app --help

# If project is named "chatbot"
chatbot --help
```

### Component CLIs

Components that add CLI capabilities to your generated projects:

**Scheduler** - `my-app tasks`

Manage scheduled tasks with persistent job tracking:

```bash
my-app tasks list       # List all scheduled jobs
my-app tasks stats      # View scheduler statistics
my-app tasks history    # View execution history
```

**→ [Complete Scheduler CLI Reference](components/scheduler/cli.md)**

**Worker** - Backend-specific CLI

Background task processing with Redis-backed queues. Commands depend on your selected backend:

**arq (default):**
```bash
arq my_project.components.worker.queues.system.WorkerSettings   # Start worker
arq --watch my_project.components.worker.queues.system.WorkerSettings  # Auto-reload
```

**Dramatiq:**
```bash
dramatiq app.components.worker.broker \
  app.components.worker.queues.system \
  app.components.worker.queues.load_test \
  --queues system load_test
```

**TaskIQ:**
```bash
taskiq worker app.components.worker.queues.system:broker
```

**→ [Complete Worker CLI Reference](components/worker/index.md#cli-commands)**

### Service CLIs

Services that add CLI capabilities to your generated projects:

**Auth Service** - `my-app auth`

User management and testing utilities:

```bash
my-app auth create-test-user   # Create single test user
my-app auth create-test-users  # Create multiple test users
my-app auth list-users         # List all users
```

**→ [Complete Auth CLI Reference](services/auth/cli.md)**

**AI Service** - `my-app ai`

Multi-provider AI chat interface with conversation management:

```bash
my-app ai status               # Show configuration and validation
my-app ai providers            # List all 7 AI providers
my-app ai chat "Hello"         # Send single message
my-app ai chat                 # Interactive chat session
my-app ai conversations        # List user conversations
my-app ai history <id>         # View conversation history
```

**→ [Complete AI CLI Reference](services/ai/cli.md)**

**Blog Service** - `my-app blog`

Inspect posts and tags, transition post state, and manage taxonomy:

```bash
my-app blog status                       # Counts and latest activity
my-app blog posts --status draft         # List posts (filter by status/tag)
my-app blog post <slug>                  # Show one post's metadata
my-app blog publish <slug>               # Draft/archived to published
my-app blog archive <slug>               # Hide from the public site
my-app blog delete <slug> --yes          # Permanent delete
my-app blog tags                         # List tags
my-app blog tag-create "Release Notes"   # Create a tag
```

**→ [Complete Blog CLI Reference](services/blog/cli.md)**

---

## Project Structure

Projects created with `aegis init` follow this structure:

```
my-project/
├── app/
│   ├── components/
│   │   ├── backend/        # FastAPI backend
│   │   ├── frontend/       # Flet frontend
│   │   ├── web_frontend/   # htmx web frontend (if included)
│   │   ├── scheduler.py    # APScheduler (if included)
│   │   ├── worker/         # Worker queues (if included)
│   │   └── database.py     # Database setup (if included)
│   ├── core/              # Framework utilities
│   ├── services/          # Business logic
│   ├── cli/               # CLI commands (if services added)
│   └── integrations/      # App composition
├── traefik/               # Traefik config (if ingress included)
│   └── traefik.yml        # Traefik static configuration
├── scripts/               # Deployment scripts (if ingress included)
│   └── server-setup.sh    # Server provisioning
├── tests/                 # Test suite
├── docs/                  # Documentation
├── data/                  # SQLite databases (if database included)
├── pyproject.toml         # Project configuration
├── Dockerfile             # Container definition
├── docker-compose.yml     # Multi-service orchestration
├── Makefile              # Development commands
└── .env.example          # Environment template
```

---

## Development Workflow

After creating a project:

```bash
cd my-project
uv sync                    # Install dependencies and create virtual environment
source .venv/bin/activate  # Activate virtual environment (important!)
cp .env.example .env       # Configure environment (edit API keys, etc.)
make serve                 # Start development server
make test                  # Run test suite
make check                 # Run all quality checks (lint + typecheck + test)
```

### Evolving Your Project

```bash
# Add components as you need them
aegis add scheduler
aegis add worker

# Add services for new features
aegis add-service auth
aegis add-service ai

# Remove components you don't need
aegis remove scheduler

# Update to latest template version
aegis update

# Always commit before making changes
git add . && git commit -m "Add scheduler component"
```

### Best Practices

1. **Commit before evolving**: Always commit your work before adding/removing components
2. **Use verbose mode**: Add `--verbose` flag to see detailed operations
3. **Test after changes**: Run `make check` after adding/removing components
4. **Review diffs**: Use `git diff` to see what changed after operations
5. **Update regularly**: Keep your project in sync with latest template via `aegis update`

---

## Environment

The CLI respects these environment variables:

- Standard Python environment variables
- UV environment variables (for dependency management)
- Project-specific variables (when running generated CLI commands)
