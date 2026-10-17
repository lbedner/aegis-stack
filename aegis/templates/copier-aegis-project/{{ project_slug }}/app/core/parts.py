"""Each part this stack can have, as the aegis CLI declares it: its kind,
its concern (``Category``), its name on the CLI, what on disk says a stack
has it, the containers it adds and where Overseer's map draws it, by the
name the app knows it by. Generated from each part's PluginSpec by ``make parts`` in
aegis-stack: change the spec, not this file. A plugin's part declares its
own ``CATEGORY`` in its package."""

from dataclasses import dataclass
from enum import StrEnum


class Category(StrEnum):
    STACK = "stack"
    COMPUTE = "compute"
    DATA = "data"
    AI = "ai"
    APP = "app"
    PLATFORM = "platform"


@dataclass(frozen=True)
class Part:
    kind: str  # component or service
    category: Category
    cli: str  # its name to the aegis CLI
    marker: str = ""  # a path only a stack with it has; empty: every stack
    containers: tuple[str, ...] = ()  # the compose services it adds
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


PARTS: dict[str, Part] = {
    "ai": Part(
        kind="service",
        category=Category.AI,
        cli="ai",
        marker="app/services/ai",
        order=20,
        description="AI platform: multi-provider chat, agents, and an LLM catalog",
    ),
    "auth": Part(
        kind="service",
        category=Category.APP,
        cli="auth",
        marker="app/services/auth",
        order=10,
        description="User authentication and authorization with JWT tokens",
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
        description="FastAPI backend server",
    ),
    "blog": Part(
        kind="service",
        category=Category.APP,
        cli="blog",
        marker="app/services/blog",
        order=90,
        description="Markdown blog with draft/publish workflow and tags",
    ),
    "browser": Part(
        kind="component",
        category=Category.COMPUTE,
        cli="browser",
        marker="app/components/browser",
        containers=("browser",),
        tier=2,
        order=120,
        description="Remote-driven browser (Playwright server)",
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
        description="Redis cache and message broker",
    ),
    "comms": Part(
        kind="service",
        category=Category.APP,
        cli="comms",
        marker="app/services/comms",
        order=30,
        description="Communications service with email, SMS and voice",
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
        description="Database with SQLModel ORM (SQLite or PostgreSQL)",
    ),
    "deploy": Part(
        kind="component",
        category=Category.STACK,
        cli="deploy",
        marker="app/components/deploy",
        containers=("socket-proxy",),
        description="Deployment target (Docker Compose), read by the Overseer",
    ),
    "documents": Part(
        kind="service",
        category=Category.DATA,
        cli="documents",
        marker="app/services/documents",
        order=40,
        description="Document store: keep the paper, deduped and findable",
    ),
    "finance": Part(
        kind="service",
        category=Category.APP,
        cli="finance",
        marker="app/services/finance",
        order=80,
        description="Personal finance aggregation (accounts, transactions, net worth, import)",
    ),
    "frontend": Part(
        kind="component",
        category=Category.APP,
        cli="frontend",
        order=30,
        description="Flet frontend interface",
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
        description="Traefik reverse proxy and load balancer",
    ),
    "insights": Part(
        kind="service",
        category=Category.APP,
        cli="insights",
        marker="app/services/insights",
        order=60,
        description="Adoption metrics and analytics with automated data collection",
    ),
    "mcp": Part(
        kind="component",
        category=Category.AI,
        cli="mcp",
        marker="app/components/mcp",
        description="MCP server: an outside assistant reads the app's tools",
    ),
    "meetings": Part(
        kind="service",
        category=Category.AI,
        cli="meetings",
        marker="app/services/meetings",
        order=55,
        description="A bot that joins calls and keeps the transcript",
    ),
    "observability": Part(
        kind="component",
        category=Category.PLATFORM,
        cli="observability",
        marker="app/components/backend/middleware/logfire_tracing.py",
        order=100,
        description="Logfire observability, tracing, and metrics",
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
        description="Local model serving (Ollama)",
    ),
    "payment": Part(
        kind="service",
        category=Category.APP,
        cli="payment",
        marker="app/services/payment",
        order=70,
        description="Payment processing with Stripe (checkout, subscriptions, webhooks)",
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
        description="Scheduled task execution infrastructure",
    ),
    "secrets": Part(
        kind="component",
        category=Category.PLATFORM,
        cli="secrets",
        marker="app/components/secrets/store.py",
        holds_keys=True,
        description="Encrypted credential store (keys editable, live)",
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
        description="S3 object storage, SeaweedFS in dev",
    ),
    "web_frontend": Part(
        kind="component",
        category=Category.APP,
        cli="htmx",
        marker="app/components/web_frontend",
        order=20,
        description="Server-rendered htmx web frontend",
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
        description="Background task processing (arq, Dramatiq, or TaskIQ)",
    ),
}
