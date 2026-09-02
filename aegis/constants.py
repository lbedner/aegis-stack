"""
Constants for Aegis Stack CLI.

This module centralizes magic strings and configuration keys used throughout
the CLI to improve maintainability and reduce duplication.
"""

# Published documentation site (mkdocs ``site_url``). Joined with each
# spec's ``docs_path`` to build the terminal hyperlinks in the guided setup.
DOCS_BASE_URL = "https://docs.aegis-stack.io/"


class ComponentNames:
    """Standard component names used throughout the CLI."""

    REDIS = "redis"
    WORKER = "worker"
    SCHEDULER = "scheduler"
    DATABASE = "database"
    BACKEND = "backend"
    FRONTEND = "frontend"
    HTMX = "htmx"
    INGRESS = "ingress"
    OBSERVABILITY = "observability"
    STORAGE = "storage"

    # Ordered list for interactive selection. Worker leads and redis
    # follows the steps that auto-add it (worker bundles redis), so most
    # users never see the redis question; scheduler/database sit early
    # because their answers fix the project's database engine, which
    # later questions (AI storage) reuse.
    INFRASTRUCTURE_ORDER = [
        WORKER,
        SCHEDULER,
        DATABASE,
        REDIS,
        STORAGE,
        INGRESS,
        OBSERVABILITY,
        HTMX,
    ]


class ServiceNames:
    """Migration-registry names for in-tree services.

    These key ``MIGRATION_SPECS`` and drive the spec-variant resolution in
    ``aegis.core.migration_generator._resolve_spec`` (per-user insights,
    schema-qualified finance). Distinct from ``ServiceType``, which
    classifies a service rather than naming its migration.
    """

    INSIGHTS = "insights"
    FINANCE = "finance"
    FINANCE_AUTH_LINK = "finance_auth_link"


class StorageBackends:
    """Storage backend options used by scheduler and database."""

    MEMORY = "memory"
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DatabaseSchemas:
    """Postgres schema names owned by in-tree services and components.

    Schemas are a Postgres feature: SQLite has no equivalent, so
    ``_resolve_spec`` strips a spec's schema for any non-Postgres engine
    and the same declaration renders correctly on both.
    """

    PUBLIC = "public"
    FINANCE = "finance"
    SCHEDULER = "scheduler"


class PostgresProviders:
    """Provider/host for a PostgreSQL database engine.

    Neon is not a separate engine, it is a place to run Postgres. ``container``
    runs a local postgres:16 service (dev and prod); ``neon`` targets Neon
    serverless Postgres (cloud) in production while still using the local
    container for development.
    """

    CONTAINER = "container"
    NEON = "neon"

    ALL = [CONTAINER, NEON]

    DEFAULT = CONTAINER


class WorkerBackends:
    """Worker backend options for task processing."""

    ARQ = "arq"
    TASKIQ = "taskiq"
    DRAMATIQ = "dramatiq"

    ALL = [ARQ, TASKIQ, DRAMATIQ]


class AIFrameworks:
    """AI framework options for the AI service."""

    PYDANTIC_AI = "pydantic-ai"
    LANGCHAIN = "langchain"

    ALL = [PYDANTIC_AI, LANGCHAIN]


class AIProviders:
    """AI provider options for the AI service."""

    # Provider identifiers
    PUBLIC = "public"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    GROQ = "groq"
    MISTRAL = "mistral"
    COHERE = "cohere"
    OLLAMA = "ollama"

    # All valid providers (used for validation)
    ALL = {PUBLIC, OPENAI, ANTHROPIC, GOOGLE, GROQ, MISTRAL, COHERE, OLLAMA}

    # Default providers for bracket syntax (non-interactive)
    DEFAULT = [PUBLIC]

    # Default providers for interactive mode. LLM7.io (the "public"
    # provider) is the only one that works immediately with no signup or
    # API key, so it is the only default.
    INTERACTIVE_DEFAULTS = [PUBLIC]

    # Provider display information: (id, display_name, description, pricing, is_recommended)
    # Only LLM7.io is recommended/pre-checked: everything else (including
    # Ollama, which needs a local install) is a deliberate opt-in. Pricing
    # notes verified 2026-06: Google's free tier covers Flash models only
    # since April 2026; Groq's free tier survives the Nvidia licensing deal.
    PROVIDER_INFO: list[tuple[str, str, str, str, bool]] = [
        (PUBLIC, "LLM7.io", "Free public endpoint", "Free, no API key", True),
        (OPENAI, "OpenAI", "GPT models", "Paid", False),
        (ANTHROPIC, "Anthropic", "Claude models", "Paid", False),
        (GOOGLE, "Google", "Gemini models", "Free tier (Flash only)", False),
        (GROQ, "Groq", "Fast inference", "Free tier", False),
        (MISTRAL, "Mistral", "Open models", "Mostly paid", False),
        (COHERE, "Cohere", "Enterprise focus", "Limited free", False),
        (OLLAMA, "Ollama", "Local inference", "Free (local)", False),
    ]


class PaymentProviders:
    """Payment provider options for the payment service."""

    STRIPE = "stripe"

    ALL = [STRIPE]

    DEFAULT = STRIPE


class OllamaMode:
    """Ollama deployment mode options."""

    HOST = "host"  # Connect to Ollama running on host machine
    DOCKER = "docker"  # Run Ollama in Docker container
    NONE = "none"  # No Ollama (using cloud provider)

    ALL = [HOST, DOCKER, NONE]

    # Default URLs for each mode
    HOST_URL = "http://host.docker.internal:11434"  # For Mac/Windows Docker
    DOCKER_URL = "http://ollama:11434"  # For Docker service


class AuthLevels:
    """Auth level options for the auth service."""

    BASIC = "basic"
    RBAC = "rbac"
    ORG = "org"

    ALL = [BASIC, RBAC, ORG]


class AnswerKeys:
    """Keys in Copier .copier-answers.yml configuration."""

    ANSWERS_FILENAME = ".copier-answers.yml"

    # Component include flags
    HTMX = "include_htmx"
    SCHEDULER = "include_scheduler"
    WORKER = "include_worker"
    REDIS = "include_redis"
    DATABASE = "include_database"
    CACHE = "include_cache"
    INGRESS = "include_ingress"
    OBSERVABILITY = "include_observability"
    STORAGE = "include_storage"

    # Service include flags
    AUTH = "include_auth"
    AI = "include_ai"
    COMMS = "include_comms"
    INSIGHTS = "include_insights"
    PAYMENT = "include_payment"
    BLOG = "include_blog"
    FINANCE = "include_finance"
    DOCUMENTS = "include_documents"

    # Service names (used for selection/lookup)
    SERVICE_AUTH = "auth"
    SERVICE_AI = "ai"
    SERVICE_COMMS = "comms"
    SERVICE_INSIGHTS = "insights"
    SERVICE_PAYMENT = "payment"
    SERVICE_BLOG = "blog"
    SERVICE_FINANCE = "finance"
    SERVICE_DOCUMENTS = "documents"

    # Insights source flags
    INSIGHTS_GITHUB = "insights_github"
    INSIGHTS_PYPI = "insights_pypi"
    INSIGHTS_PLAUSIBLE = "insights_plausible"
    INSIGHTS_REDDIT = "insights_reddit"
    INSIGHTS_PER_USER = "insights_per_user"

    # Finance source flags
    FINANCE_PLAID = "finance_plaid"
    FINANCE_SNAPTRADE = "finance_snaptrade"
    FINANCE_IMPORT = "finance_import"

    # Payment configuration
    PAYMENT_PROVIDER = "payment_provider"

    # Configuration values
    SCHEDULER_BACKEND = "scheduler_backend"
    SCHEDULER_WITH_PERSISTENCE = "scheduler_with_persistence"
    WORKER_BACKEND = "worker_backend"
    DATABASE_ENGINE = "database_engine"
    POSTGRES_PROVIDER = "postgres_provider"
    AI_FRAMEWORK = "ai_framework"
    AI_PROVIDERS = "ai_providers"
    AI_BACKEND = "ai_backend"
    AI_WITH_PERSISTENCE = "ai_with_persistence"
    AI_RAG = "ai_rag"
    AUTH_LEVEL = "auth_level"
    AUTH_RBAC = "include_auth_rbac"
    AUTH_ORG = "include_auth_org"
    AUTH_OAUTH = "include_oauth"
    AI_VOICE = "ai_voice"
    OLLAMA_MODE = "ollama_mode"
    PROJECT_SLUG = "project_slug"
    SRC_PATH = "_src_path"

    @classmethod
    def include_key(cls, name: str) -> str:
        """Generate include key for component/service name."""
        return f"include_{name}"


class Messages:
    """User-facing CLI messages."""

    # Section headers and separators
    SEPARATOR_WIDTH = 40
    SEPARATOR = "=" * SEPARATOR_WIDTH

    SECTION_COMPONENT_SELECTION = "Component Selection"
    SECTION_SERVICE_SELECTION = "Service Selection"
    SECTION_COMPONENT_REMOVAL = "Component Removal"
    SECTION_SERVICE_REMOVAL = "Service Removal Selection"
    SECTION_SCHEDULER_PERSISTENCE = "Scheduler Persistence"
    SECTION_DATABASE_ENGINE = "Database Engine"
    SECTION_AI_FRAMEWORK = "AI Framework Selection"
    SECTION_AI_BACKEND = "AI Conversation Persistence"
    SECTION_AI_PROVIDERS = "AI Provider Selection"

    # Git validation
    GIT_NOT_INITIALIZED = "Project is not in a git repository"
    GIT_REQUIRED_HINT = "Copier updates require git for change tracking"
    GIT_INIT_HINT = (
        "Projects created with 'aegis init' should have git initialized automatically"
    )
    GIT_MANUAL_INIT = (
        "If you created this project manually, run: "
        "git init && git add . && git commit -m 'Initial commit'"
    )

    # Copier project validation
    NOT_COPIER_PROJECT = "Project was not generated with Copier"

    # Component/service parsing
    EMPTY_COMPONENT_NAME = "Empty component name is not allowed"
    EMPTY_SERVICE_NAME = "Empty service name is not allowed"

    # Interactive mode
    INTERACTIVE_IGNORES_ARGS = "Warning: --interactive flag ignores component arguments"
    NO_COMPONENTS_SELECTED = "No components selected"
    NO_SERVICES_SELECTED = "No services selected"

    # Next steps messages
    NEXT_STEPS_HEADER = "Next steps:"
    NEXT_STEP_MAKE_CHECK = "   1. Run 'make check' to verify the update"
    NEXT_STEP_TEST = "   2. Test your application"
    NEXT_STEP_COMMIT = "   3. Commit the changes with: git add . && git commit"

    REVIEW_CHANGES_HEADER = "Review changes:"
    REVIEW_DOCKER_COMPOSE = "   git diff docker-compose.yml"
    REVIEW_PYPROJECT = "   git diff pyproject.toml"

    @classmethod
    def copier_only_command(cls, command_name: str) -> str:
        """Generate message for Copier-only command."""
        from .i18n import t

        return t("shared.copier_only", command=command_name)

    @classmethod
    def print_section_header(cls, title: str, newline_before: bool = False) -> None:
        """Print a section header with separator."""
        import typer

        if newline_before:
            typer.echo()
        typer.echo(title)
        typer.echo(cls.SEPARATOR)

    @classmethod
    def print_next_steps(cls) -> None:
        """Print standard next steps message."""
        import typer

        from .i18n import t

        typer.echo(f"\n{t('shared.next_steps')}")
        typer.echo(t("shared.next_make_check"))
        typer.echo(t("shared.next_test"))
        typer.echo(t("shared.next_commit"))

    @classmethod
    def print_review_changes(cls) -> None:
        """Print standard review changes message."""
        import typer

        from .i18n import t

        typer.echo(f"\n{t('shared.review_header')}")
        typer.echo(t("shared.review_docker"))
        typer.echo(t("shared.review_pyproject"))
