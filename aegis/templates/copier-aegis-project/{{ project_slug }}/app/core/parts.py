"""Each part this stack can have, as the aegis CLI declares it: its kind,
its concern (``Category``), its name on the CLI, what on disk says a stack
has it, the containers it adds and where Overseer's map draws it, by the
name the app knows it by. Generated from each part's PluginSpec by ``make parts`` in
aegis-stack: change the spec, not this file. A plugin's part declares its
own ``CATEGORY`` in its package."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class Category(StrEnum):
    STACK = "stack"
    COMPUTE = "compute"
    DATA = "data"
    AI = "ai"
    APP = "app"
    PLATFORM = "platform"


@dataclass(frozen=True)
class Option:
    """One way a part can be built: the ontology's ``PartOption`` without
    this stack's choice, which ``answer`` keys in ``.copier-answers.yml``."""

    name: str
    mode: Literal["single", "multi", "flag"]
    choices: tuple[str, ...]
    default: str | tuple[str, ...] | bool | None = None
    answer: str = ""
    ordered: bool = False
    about: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Part:
    kind: str  # component or service
    category: Category
    cli: str  # its name to the aegis CLI
    marker: str = ""  # a path only a stack with it has; empty: every stack
    containers: tuple[str, ...] = ()  # the compose services it adds
    # Dev-only services that act on the developer's machine for Overseer
    # (deploy-agent): shown on its page and in its logs, never on the map.
    agents: tuple[str, ...] = ()
    # Overseer's map: its row as a process of its own (0 the edge, 1 the
    # app, 2 its data; None: inside the webserver), data's shape (store,
    # bucket), the parts it calls and the ones it takes work from.
    tier: int | None = None
    page: str = ""  # its Overseer page, where that is not its name
    role: str = ""
    depends_on: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    hosts: bool = False  # what has no process of its own runs in it
    holds_keys: bool = False  # every outside provider's key lives in it
    order: int | None = None  # in the sidebar and its row; none: last, by name
    # What it is, in a line: what the app map says of a part with no
    # package docstring of its own (ingress is Traefik, not Python).
    description: str = ""
    # Its schema, APIs and CLI may change between releases.
    experimental: bool = False
    options: tuple[Option, ...] = ()  # what else it could be


PARTS: dict[str, Part] = {
    "ai": Part(
        kind="service",
        category=Category.AI,
        cli="ai",
        marker="app/services/ai",
        order=20,
        description="Conversational agents, RAG, model catalog, TTS and STT (PydanticAI / LangChain across 7 providers)",
        options=(
            Option(
                name="framework",
                mode="single",
                choices=("pydantic-ai", "langchain"),
                default="pydantic-ai",
                answer="ai_framework",
                about=(
                    ("pydantic-ai", "Typed and lightweight. The default."),
                    ("langchain", "Large ecosystem, many integrations."),
                ),
            ),
            Option(
                name="backend",
                mode="single",
                choices=("memory", "sqlite", "postgres"),
                default="memory",
                answer="ai_backend",
                about=(
                    ("memory", "No history, nothing to set up."),
                    ("sqlite", "Persistent chat history in a file database."),
                    ("postgres", "Persistent and production-grade."),
                ),
            ),
            Option(
                name="providers",
                mode="multi",
                choices=(
                    "anthropic",
                    "cohere",
                    "google",
                    "groq",
                    "mistral",
                    "ollama",
                    "openai",
                    "public",
                ),
                default=("public",),
                answer="ai_providers",
                about=(
                    ("anthropic", "Claude models (Paid)"),
                    ("cohere", "Enterprise focus (Limited free)"),
                    ("google", "Gemini models (Free tier (Flash only))"),
                    ("groq", "Fast inference (Free tier)"),
                    ("mistral", "Open models (Mostly paid)"),
                    ("ollama", "Local inference (Free (local))"),
                    ("openai", "GPT models (Paid)"),
                    ("public", "Free public endpoint (Free, no API key)"),
                ),
            ),
            Option(name="rag", mode="flag", choices=("rag",), answer="ai_rag"),
            Option(name="voice", mode="flag", choices=("voice",), answer="ai_voice"),
        ),
    ),
    "auth": Part(
        kind="service",
        category=Category.APP,
        cli="auth",
        marker="app/services/auth",
        order=10,
        description="Persistent sessions with refresh-token rotation, GitHub/Google sign-in, RBAC, multi-tenant Organizations",
        options=(
            Option(
                name="level",
                mode="single",
                choices=("basic", "rbac", "org"),
                default="basic",
                answer="auth_level",
                ordered=True,
                about=(
                    ("basic", "Email and password with JWT sessions."),
                    ("rbac", "Adds roles and permissions."),
                    ("org", "Multi-tenant organizations."),
                ),
            ),
            Option(name="engine", mode="single", choices=("sqlite", "postgres")),
            Option(
                name="oauth", mode="flag", choices=("oauth",), answer="include_oauth"
            ),
        ),
    ),
    "backend": Part(
        kind="component",
        category=Category.COMPUTE,
        cli="backend",
        containers=("webserver",),
        tier=1,
        page="server",
        depends_on=("database", "queue", "cache", "storage", "ollama", "browser"),
        hosts=True,
        order=10,
        description="FastAPI on uvicorn or granian, lifecycle hooks, in-memory request metrics, API load testing for every route",
    ),
    "blog": Part(
        kind="service",
        category=Category.APP,
        cli="blog",
        marker="app/services/blog",
        order=90,
        description="Markdown publishing with drafts, tags, and an Overseer editor",
    ),
    "browser": Part(
        kind="component",
        category=Category.COMPUTE,
        cli="browser",
        marker="app/components/browser",
        containers=("browser",),
        tier=2,
        order=120,
        description="Remote Chromium in its own container, driven over Playwright: JavaScript pages, sign-ins, a bot that joins a meeting",
    ),
    "cache": Part(
        kind="component",
        category=Category.DATA,
        cli="redis",
        marker="app/components/frontend/dashboard/cards/redis_card.py",
        containers=("redis",),
        tier=2,
        page="redis",
        role="store",
        order=70,
        description="Redis for caching, sessions, pub/sub",
    ),
    "comms": Part(
        kind="service",
        category=Category.APP,
        cli="comms",
        marker="app/services/comms",
        order=30,
        description="Transactional email (Resend) + SMS / voice (Twilio)",
    ),
    "database": Part(
        kind="component",
        category=Category.DATA,
        cli="database",
        marker="app/core/db.py",
        containers=("postgres",),
        tier=2,
        role="store",
        order=40,
        description="Postgres (self-hosted or Neon serverless) or SQLite + SQLModel ORM",
        options=(
            Option(
                name="engine",
                mode="single",
                choices=("sqlite", "postgres"),
                default="sqlite",
                answer="database_engine",
                about=(
                    ("sqlite", "Zero-config file database. Great for development."),
                    ("postgres", "Production-grade, pooled connections."),
                ),
            ),
            Option(
                name="provider",
                mode="single",
                choices=("container", "neon"),
                default="container",
                answer="postgres_provider",
                about=(
                    ("container", "Local postgres:16 container, dev and prod."),
                    (
                        "neon",
                        "Serverless Postgres: cloud in prod, local container in dev.",
                    ),
                ),
            ),
        ),
    ),
    "deploy": Part(
        kind="component",
        category=Category.STACK,
        cli="deploy",
        marker="app/components/deploy",
        containers=("socket-proxy",),
        agents=("deploy-agent",),
        page="deployments",
        description="Deployment target (Docker Compose), read by the Overseer",
        options=(
            Option(
                name="target",
                mode="single",
                choices=("compose",),
                default="compose",
                answer="deploy_target",
            ),
        ),
    ),
    "documents": Part(
        kind="service",
        category=Category.DATA,
        cli="documents",
        marker="app/services/documents",
        order=40,
        description="Content-addressed document store, deduped, with page-addressed extraction",
    ),
    "finance": Part(
        kind="service",
        category=Category.APP,
        cli="finance",
        marker="app/services/finance",
        order=80,
        description="Personal finance aggregation (accounts, transactions, net worth, import)",
        experimental=True,
    ),
    "frontend": Part(
        kind="component",
        category=Category.APP,
        cli="frontend",
        order=30,
        description="Flet, ships with the Overseer system dashboard",
    ),
    "ingress": Part(
        kind="component",
        category=Category.COMPUTE,
        cli="ingress",
        marker="traefik",
        containers=("traefik",),
        tier=0,
        depends_on=("backend",),
        order=90,
        description="Traefik v3 reverse proxy with TLS",
    ),
    "insights": Part(
        kind="service",
        category=Category.APP,
        cli="insights",
        marker="app/services/insights",
        order=60,
        description="Adoption metrics across GitHub, PyPI, Plausible, Reddit",
        options=(
            Option(
                name="sources",
                mode="multi",
                choices=("github", "pypi", "plausible", "reddit"),
                default=("github", "pypi"),
            ),
            Option(name="per_user", mode="flag", choices=("per_user",)),
        ),
    ),
    "mcp": Part(
        kind="component",
        category=Category.AI,
        cli="mcp",
        marker="app/components/mcp",
        description="Serves the app's own tools to Claude Desktop, Claude Code or a local model over MCP: the tools you grant, never a write",
    ),
    "meetings": Part(
        kind="service",
        category=Category.AI,
        cli="meetings",
        marker="app/services/meetings",
        agents=("meetings-runner",),
        order=55,
        description="A bot that joins Google Meet as its own agent: transcript, notes, threads, people, what keeps coming up, joined from its calendar",
        experimental=True,
    ),
    "observability": Part(
        kind="component",
        category=Category.PLATFORM,
        cli="observability",
        marker="app/components/backend/middleware/logfire_tracing.py",
        order=100,
        description="Pydantic Logfire tracing + metrics + logging",
    ),
    "ollama": Part(
        kind="component",
        category=Category.AI,
        cli="inference",
        marker="app/components/inference/ollama.py",
        containers=("ollama",),
        tier=2,
        page="inference",
        order=110,
        description="Local AI models via Ollama",
        options=(
            Option(
                name="engine",
                mode="single",
                choices=("ollama",),
                default="ollama",
                answer="inference_engine",
            ),
            Option(
                name="placement",
                mode="single",
                choices=("host", "docker"),
                default="host",
                answer="inference_placement",
                about=(
                    (
                        "host",
                        "Use the Ollama already running on this machine. The default.",
                    ),
                    (
                        "docker",
                        "Run Ollama as a container in the project's compose stack.",
                    ),
                ),
            ),
        ),
    ),
    "payment": Part(
        kind="service",
        category=Category.APP,
        cli="payment",
        marker="app/services/payment",
        order=70,
        description="Stripe checkout, subscriptions, refunds, disputes",
        options=(
            Option(
                name="provider",
                mode="single",
                choices=("stripe",),
                default="stripe",
                answer="payment_provider",
            ),
        ),
    ),
    "research": Part(
        kind="service",
        category=Category.AI,
        cli="research",
        marker="app/services/research",
        order=50,
        description="Outside posts and threads, collected by saved searches",
    ),
    "scheduler": Part(
        kind="component",
        category=Category.COMPUTE,
        cli="scheduler",
        marker="app/components/scheduler",
        containers=("scheduler",),
        tier=1,
        depends_on=("database", "queue"),
        order=60,
        description="APScheduler with persistent jobs",
        options=(
            Option(
                name="backend",
                mode="single",
                choices=("memory", "sqlite", "postgres"),
                default="memory",
                answer="scheduler_backend",
                about=(
                    (
                        "memory",
                        "No persistence. Jobs reset on restart — skip if unsure.",
                    ),
                    ("sqlite", "Persist job history in a file database."),
                    ("postgres", "Persist job history, production-grade."),
                ),
            ),
        ),
    ),
    "secrets": Part(
        kind="component",
        category=Category.PLATFORM,
        cli="secrets",
        marker="app/components/secrets/store.py",
        holds_keys=True,
        description="Encrypted credential store: keys set while the app runs, checked with the provider on paste, never shown again",
        options=(
            Option(
                name="backend",
                mode="single",
                choices=("database",),
                default="database",
                answer="secrets_backend",
            ),
        ),
    ),
    "storage": Part(
        kind="component",
        category=Category.DATA,
        cli="storage",
        marker="app/components/storage",
        containers=("seaweedfs",),
        tier=2,
        role="bucket",
        order=80,
        description="S3 object storage for the files an app keeps, SeaweedFS in dev",
    ),
    "web_frontend": Part(
        kind="component",
        category=Category.APP,
        cli="htmx",
        marker="app/components/web_frontend",
        order=20,
        description="Server-rendered pages at `/`: Jinja2 + htmx + Alpine, Tailwind/DaisyUI styling",
    ),
    "worker": Part(
        kind="component",
        category=Category.COMPUTE,
        cli="worker",
        marker="app/components/worker",
        containers=("worker-system", "worker-load-test"),
        tier=1,
        depends_on=("queue", "database"),
        consumes=("queue",),
        order=50,
        description="Pluggable Arq, Taskiq, or Dramatiq",
        options=(
            Option(
                name="backend",
                mode="single",
                choices=("arq", "taskiq", "dramatiq"),
                default="arq",
                answer="worker_backend",
                about=(
                    (
                        "arq",
                        "Simple, well-tested async worker with minimal configuration. Best for I/O-bound tasks. The default.",
                    ),
                    (
                        "taskiq",
                        "Async-native with per-queue brokers and Redis Streams transport with acknowledgements.",
                    ),
                    (
                        "dramatiq",
                        "Multi-process actor model. Best for CPU-bound tasks that benefit from multiple OS processes.",
                    ),
                ),
            ),
        ),
    ),
}
