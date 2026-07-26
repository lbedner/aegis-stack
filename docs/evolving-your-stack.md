# Evolving Your Stack

**Your architecture isn't set in stone.** Build for today's requirements, adapt as they change, refactor when needed.

Most project starters lock you into decisions made during `init`. Aegis Stack gives you the freedom to evolve your stack as your product evolves.

---

## The Friday Afternoon Dilemma

It's Friday afternoon. Product wants the MVP Monday.

![Management has spoken](images/mr_burns.jpg)

Do you:

**A) Over-engineer for "future scale"** *(workers, queues, caching, message buses...)*

**B) Ship the minimal viable stack** *(FastAPI + Flet, with an htmx web frontend one `aegis add htmx` away)*

With Aegis Stack, you can confidently choose **B** - because adding components later is trivial.

```bash
# Friday 4 PM: Bootstrap it
uvx aegis-stack init mvp-api
cd mvp-api && uv sync && make serve

# Monday 9 AM: It's live
```

---

## Week 3: Your First Background Job

Product loves the MVP. Now they want automated daily reports.

**Before Aegis Stack:**

- Manually add APScheduler dependency
- Create scheduler infrastructure
- Configure Docker services
- Update docker-compose.yml
- Fight merge conflicts
- Cross fingers

**With Aegis Stack:**

```bash
aegis add scheduler --project-path ./mvp-api
```

**Added:**

- `app/entrypoints/scheduler.py` - Scheduler entrypoint
- `app/components/scheduler.py` - Job registration
- `tests/components/test_scheduler.py` - Component tests
- Docker service configuration
- Health check integration

**Updated:**

- `docker-compose.yml` - New scheduler service
- `pyproject.toml` - APScheduler dependency
- `.copier-answers.yml` - Component state

**Ran automatically:**

- `uv sync` - Installed dependencies
- `make fix` - Formatted code

### Your First Scheduled Job

Now add your daily report:

```python
# app/components/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler

def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all scheduled jobs."""

    # Daily report at 9 AM
    scheduler.add_job(
        generate_daily_report,
        trigger="cron",
        hour=9,
        minute=0,
        id="daily_report",
        name="Generate Daily Report",
        replace_existing=True,
    )

async def generate_daily_report() -> None:
    """Generate and send daily report."""
    # Your logic here
    pass
```

Ship it:
```bash
git add . && git commit -m "Add daily reports"
docker compose up -d
```

---

## Month 2: Scaling Up

Traffic is growing. Some API endpoints are slow. Time for background processing.

```bash
aegis add worker --project-path ./mvp-api
```

**Added:**

- `app/components/worker/` - Worker queues (system, load-test)
- `app/services/load_test.py` - Load testing service
- Redis service (auto-included dependency)
- Worker health monitoring

**Updated:**

- `docker-compose.yml` - Redis + worker services
- `pyproject.toml` - arq + redis dependencies

### Move Work to Background

```python
# app/components/backend/api/reports.py

from fastapi import APIRouter
from arq import create_pool
from arq.connections import RedisSettings

router = APIRouter()

@router.post("/reports/generate")
async def generate_report_async(report_data: dict):
    """Queue report generation."""
    redis = await create_pool(RedisSettings())
    job = await redis.enqueue_job("generate_report", report_data)

    return {"job_id": str(job.job_id), "status": "queued"}
```

```python
# app/components/worker/queues/system.py

async def generate_report(ctx: dict, report_data: dict) -> dict:
    """Process report generation in background."""
    # Heavy lifting happens here
    report = await process_report(report_data)
    await send_report_email(report)
    return {"status": "complete", "report_id": report.id}
```

---

## Month 4: Adding User Authentication

Product wants to add user accounts. You need authentication.

**Before Aegis Stack:**

- Research auth libraries
- Set up database models
- Create migration system
- Build JWT token handling
- Write auth endpoints
- Add password hashing
- Configure environment variables
- Test everything manually

**With Aegis Stack:**

```bash
aegis add-service auth --project-path ./mvp-api
```

**Added:**

- `app/components/backend/api/auth/` - Auth API endpoints (login, register, etc.)
- `app/models/user.py` - User model with password hashing
- `app/services/auth/` - Authentication service layer
- `app/core/security.py` - JWT token handling
- `app/cli/auth.py` - User management CLI commands
- `alembic/` - Database migration infrastructure
- `tests/` - Comprehensive auth test suite (52 tests)
- Database component (auto-added as required dependency)

**Updated:**

- `pyproject.toml` - Auth dependencies (python-jose, passlib, python-multipart)
- `.env.example` - Auth configuration (JWT_SECRET, etc.)
- `docker-compose.yml` - No changes (database already there from worker)

### Post-Addition Setup

```bash
# Apply auth migrations
make migrate

# Create test users
mvp-api auth create-test-users --count 5

# Test authentication
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "admin123"}'
```

### Using Auth in Your API

```python
# app/components/backend/api/reports.py

from fastapi import APIRouter, Depends
from app.components.backend.api.deps import get_current_active_user
from app.models.user import User

router = APIRouter()

@router.post("/reports/generate")
async def generate_report_async(
    report_data: dict,
    current_user: User = Depends(get_current_active_user)  # Protected!
):
    """Queue report generation (requires authentication)."""
    redis = await create_pool(RedisSettings())
    job = await redis.enqueue_job(
        "generate_report",
        report_data,
        user_id=current_user.id  # Track who requested it
    )

    return {"job_id": str(job.job_id), "status": "queued"}
```

---

## Month 5: Adding AI Chat

Product wants an AI chatbot for customer support.

```bash
aegis add-service ai --project-path ./mvp-api
```

**Added:**

- `app/services/ai/` - PydanticAI integration with multiple providers
- `app/components/backend/api/v1/ai/` - AI API endpoints (chat, streaming)
- `app/cli/ai.py` - Interactive CLI chat interface with markdown rendering
- AI provider support (OpenAI, Anthropic, Google Gemini, Groq)
- Conversation persistence and memory management

**Updated:**

- `pyproject.toml` - PydanticAI dependencies
- `.env.example` - AI provider configuration

### Post-Addition Setup

```bash
# Configure AI provider
echo "AI_PROVIDER=openai" >> .env
echo "OPENAI_API_KEY=your-key-here" >> .env

# Test via CLI
mvp-api ai chat
# > How can I help you today?
# Hello! Can you explain webhooks?

# Test via API
curl -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Explain webhooks", "stream": false}'
```

### Combining Services: AI + Auth

```python
# app/components/backend/api/v1/ai/router.py

from fastapi import APIRouter, Depends
from app.components.backend.api.deps import get_current_active_user
from app.models.user import User
from app.services.ai import get_ai_response

router = APIRouter()

@router.post("/api/v1/ai/chat")
async def chat(
    message: str,
    current_user: User = Depends(get_current_active_user)  # Require auth
):
    """User-specific AI chat with conversation history."""
    response = await get_ai_response(
        message=message,
        user_id=current_user.id  # Personalized context
    )

    return {"response": response, "user": current_user.email}
```

---

## Month 6: Refactoring

You've learned your system. Turns out scheduled jobs work better as worker tasks. Time to clean up.

```bash
aegis remove scheduler --project-path ./mvp-api
```

**Removed:**

- All scheduler component files
- Scheduler Docker service
- APScheduler dependency

**Updated:**

- `docker-compose.yml` - Scheduler service gone
- `pyproject.toml` - Dependency cleaned up

**Preserved:**

- All your business logic (you migrated it to workers)
- Database data (if scheduler was using SQLite)
- Git history (full rollback support)

### Migration Pattern

**Before removal**, move jobs to workers:

```python
# app/components/worker/queues/system.py

from arq import cron

# Daily report - now a worker cron job
async def generate_daily_report(ctx):
    """Generate and send daily report."""
    # Your logic here
    pass

class WorkerSettings:
    cron_jobs = [
        cron(generate_daily_report, hour=9, minute=0)  # Daily at 9 AM
    ]
```

Then remove scheduler:
```bash
git add . && git commit -m "Migrate to worker-based scheduling"
aegis remove scheduler --project-path ./mvp-api
git add . && git commit -m "Remove scheduler component"
```

---

## Template Updates: Your Safety Net

**Most template tools abandon you at `init`. Aegis stays with you.**

Six months from now, we'll fix a security bug in our FastAPI template. Or add a better health check pattern. Or improve Docker configurations.

With most scaffolding tools? You're on your own. Manually diff templates. Copy-paste fixes. Hope nothing breaks.

With Aegis Stack:

```bash
aegis update
```

### What `aegis update` Actually Does

Powered by [Copier](https://copier.readthedocs.io/)'s **git-based 3-way merge engine**, your project stays connected to its template. When you run `aegis update`:

1. **Fetches latest template** from your configured source
2. **Compares three versions**: Original template → Your customizations → New template
3. **Merges intelligently** - template improvements flow in, your code stays intact
4. **Shows conflicts clearly** - when manual review is needed, you see exactly where

```bash
# Preview what would change
aegis update --dry-run

# Apply template updates
aegis update

# What gets updated:
# ✓ Security fixes in generated code
# ✓ Improved Docker configurations
# ✓ Better testing patterns
# ✓ Enhanced tooling setup

# What stays yours:
# ✓ Your business logic
# ✓ Custom modifications
# ✓ Database data
# ✓ Git history
```

### The Safety Guarantee

- **Non-destructive**: Your custom code is preserved through Copier's 3-way merge
- **Transparent**: `--dry-run` shows exactly what changes before applying
- **Reversible**: Full git history for rollback if needed
- **Incremental**: Small, frequent updates over painful migrations

---

## Month 7: Going Live

Your app is stable, tested, and ready for users. Time to deploy.

**Before Aegis Stack:**

- Provision a server manually
- Install Docker, configure firewall
- Write deployment scripts
- Set up a reverse proxy
- Configure TLS certificates
- Build a CI/CD pipeline

**With Aegis Stack:**

```bash
# Add the ingress component (Traefik reverse proxy)
aegis add ingress --project-path ./mvp-api
```

**Added:**

- `traefik/traefik.yml` - Traefik reverse proxy configuration
- `scripts/server-setup.sh` - Server provisioning script
- `docker-compose.prod.yml` - Production compose overrides
- Admin endpoint protection (IP allowlist middleware)
- Automatic service discovery via Docker labels

### First Deployment

```bash
# Point aegis at your server
aegis deploy-init --host 203.0.113.50

# Provision the server (Docker, firewall, directories)
aegis deploy-setup

# Ship it
aegis deploy

# Your app is live at http://203.0.113.50
```

### Adding HTTPS

```bash
# Enable TLS with Let's Encrypt
aegis ingress-enable --domain myapp.com --email admin@myapp.com

# Redeploy with TLS
aegis deploy

# Your app is live at https://myapp.com
```

### Day-to-Day Operations

```bash
# Push code changes
aegis deploy

# Check service health
aegis deploy-status

# Follow logs
aegis deploy-logs

# Debug inside a container
aegis deploy-shell

# Restart services after config change
aegis deploy-restart
```

From Friday afternoon MVP to production HTTPS deployment, all without leaving your project.

---

## Next Steps

- **[CLI Reference](cli-reference.md)** - Complete `aegis add` and `aegis remove` documentation
- **[Component Overview](components/index.md)** - Deep dive into available components
- **[Deployment Guide](deployment/index.md)** - Full deployment command reference

---

**Build for today. Adapt for tomorrow. That's Aegis Stack.**
