"""
Template generation and context building for Aegis Stack projects.

This module handles the generation of cookiecutter context and manages
the template rendering process based on selected components.
"""

from pathlib import Path
from typing import Any

from .. import __version__ as aegis_version
from ..config.defaults import DEFAULT_PYTHON_VERSION
from ..constants import (
    AIFrameworks,
    AIProviders,
    AnswerKeys,
    AuthLevels,
    ComponentNames,
    OllamaMode,
    PaymentProviders,
    PostgresProviders,
    StorageBackends,
    WorkerBackends,
)
from .ai_service_parser import is_ai_service_with_options, parse_ai_service_config
from .auth_service_parser import is_auth_service_with_options, parse_auth_service_config
from .component_utils import (
    extract_base_component_name,
    extract_base_service_name,
    extract_engine_info,
)
from .components import COMPONENTS, CORE_COMPONENTS, ComponentType
from .insights_service_parser import (
    is_insights_service_with_options,
    parse_insights_service_config,
)
from .services import SERVICES


class TemplateGenerator:
    """Handles template context generation for cookiecutter."""

    def __init__(
        self,
        project_name: str,
        selected_components: list[str],
        scheduler_backend: str = StorageBackends.MEMORY,
        selected_services: list[str] | None = None,
        python_version: str = DEFAULT_PYTHON_VERSION,
    ):
        """
        Initialize template generator.

        Args:
            project_name: Name of the project being generated
            selected_components: List of component names to include
            scheduler_backend: Scheduler backend: memory, sqlite, or postgres
            selected_services: List of service names to include
            python_version: Python version for generated project (default from pyproject.toml)
        """
        self.project_name = project_name
        self.project_slug = project_name.lower().replace(" ", "-").replace("_", "-")
        self.scheduler_backend = scheduler_backend
        self.selected_services = selected_services or []
        self.python_version = python_version

        # Always include core components
        all_components = CORE_COMPONENTS + selected_components

        # Add required components from selected services
        for service_name in self.selected_services:
            if service_name in SERVICES:
                service_spec = SERVICES[service_name]
                all_components.extend(service_spec.required_components)

        # Remove duplicates, preserve order
        self.components = list(dict.fromkeys(all_components))

        # Extract database engine from database[engine] format for template context
        self.database_engine = None
        for component in self.components:
            if extract_base_component_name(component) == ComponentNames.DATABASE:
                self.database_engine = extract_engine_info(component)
                if self.database_engine:
                    break

        # Neon is a Postgres *provider*, not a separate engine: database[neon]
        # normalizes to engine=postgres + provider=neon so every postgres template
        # path (and dependent services keying off database_engine) is reused. The
        # provider only layers on connection handling and the prod compose shape.
        self.postgres_provider = PostgresProviders.CONTAINER
        if self.database_engine == PostgresProviders.NEON:
            self.database_engine = StorageBackends.POSTGRES
            self.postgres_provider = PostgresProviders.NEON

        # Extract scheduler backend from scheduler[backend] format or use passed param
        # If scheduler[backend] syntax is used, it overrides the passed parameter
        for component in self.components:
            if extract_base_component_name(component) == ComponentNames.SCHEDULER:
                backend = extract_engine_info(component)
                if backend:
                    self.scheduler_backend = backend
                    break

        # Extract worker backend from worker[backend] format
        self.worker_backend = WorkerBackends.ARQ  # Default to arq
        for component in self.components:
            if extract_base_component_name(component) == ComponentNames.WORKER:
                backend = extract_engine_info(component)
                if backend:
                    self.worker_backend = backend
                    break

        # Extract AI config from ai[framework, backend, providers, rag, voice] format in services
        self.ai_backend = StorageBackends.MEMORY  # Default to memory
        self.ai_framework = AIFrameworks.PYDANTIC_AI  # Default to pydantic-ai
        self.ai_rag = False  # Default to no RAG
        self.ai_voice = False  # Default to no voice
        user_specified_ai_backend = False

        for service in self.selected_services:
            if extract_base_service_name(service) == AnswerKeys.SERVICE_AI:
                if is_ai_service_with_options(service):
                    ai_config = parse_ai_service_config(service)
                    self.ai_backend = ai_config.backend
                    self.ai_framework = ai_config.framework
                    self.ai_rag = ai_config.rag_enabled
                    self.ai_voice = ai_config.voice_enabled
                    user_specified_ai_backend = True
                break

        # OAuth social login (GitHub + Google) — opt-in via the
        # ``auth[oauth]`` modifier in the bracket syntax (composes with
        # ``auth[rbac,oauth]`` etc.). Defaults off so projects that
        # don't ask for it don't pay for the extra routes and deps.
        self.include_oauth: bool = False

        # Extract auth level (and oauth modifier) from auth[...] format in services
        self.auth_level = AuthLevels.BASIC  # Default to basic
        self._user_specified_auth_level = False
        for service in self.selected_services:
            if extract_base_service_name(service) == AnswerKeys.SERVICE_AUTH:
                if is_auth_service_with_options(service):
                    auth_config = parse_auth_service_config(service)
                    self.auth_level = auth_config.level
                    self._user_specified_auth_level = True
                    self.include_oauth = auth_config.oauth
                break

        # Extract insights sources + per_user flag from insights[...] format
        from .insights_service_parser import DEFAULT_SOURCES

        self.insights_sources: list[str] = DEFAULT_SOURCES.copy()
        self.insights_per_user: bool = False
        for service in self.selected_services:
            if extract_base_service_name(service) == AnswerKeys.SERVICE_INSIGHTS:
                if is_insights_service_with_options(service):
                    insights_config = parse_insights_service_config(service)
                    self.insights_sources = insights_config.sources
                    self.insights_per_user = insights_config.per_user
                break

        # Auto-detect: if AI service selected AND database available AND no explicit backend,
        # use SQLite for persistence (analytics, conversation history, LLM tracking)
        if not user_specified_ai_backend:
            has_ai = any(
                extract_base_service_name(s) == AnswerKeys.SERVICE_AI
                for s in self.selected_services
            )
            has_database = any(
                extract_base_component_name(c) == ComponentNames.DATABASE
                for c in self.components
            )
            if has_ai and has_database:
                self.ai_backend = StorageBackends.SQLITE

        # Build component specs using base names
        self.component_specs = {}
        for name in self.components:
            base_name = extract_base_component_name(name)
            if base_name in COMPONENTS:
                self.component_specs[base_name] = COMPONENTS[base_name]

    def _component_flag(self, name: str) -> str:
        """Cookiecutter "yes"/"no" for whether component ``name`` is selected.

        Base-name comparison so bracket syntax (``worker[dramatiq]``,
        ``scheduler[sqlite]``) still counts as the component.
        """
        return (
            "yes"
            if any(extract_base_component_name(c) == name for c in self.components)
            else "no"
        )

    def _service_flag(self, name: str) -> str:
        """Cookiecutter "yes"/"no" for whether service ``name`` is selected.

        Base-name comparison so bracket syntax (``ai[langchain, sqlite]``,
        ``auth[rbac]``) still counts as the service.
        """
        return (
            "yes"
            if any(extract_base_service_name(s) == name for s in self.selected_services)
            else "no"
        )

    def get_template_context(self) -> dict[str, Any]:
        """
        Generate cookiecutter context from components.

        Returns:
            Dictionary containing all template variables
        """
        # Store the originally selected components (without core)
        selected_only = [c for c in self.components if c not in CORE_COMPONENTS]

        return {
            "project_name": self.project_name,
            "project_slug": self.project_slug,
            "python_version": self.python_version,
            "aegis_version": aegis_version,
            # include_<name> flags for template conditionals, one per optional
            # component and per service, derived from the plugin registries —
            # a new spec needs no entry here. Cookiecutter-era consumers
            # expect "yes"/"no" strings.
            **{
                AnswerKeys.include_key(name): self._component_flag(name)
                for name, spec in COMPONENTS.items()
                if spec.type != ComponentType.CORE
            },
            **{
                AnswerKeys.include_key(name): self._service_flag(name)
                for name in SERVICES
            },
            # Database engine selection (sqlite or postgres)
            "database_engine": self.database_engine or StorageBackends.SQLITE,
            # Postgres provider (container vs neon); ignored for sqlite engines
            AnswerKeys.POSTGRES_PROVIDER: self.postgres_provider,
            # Scheduler backend selection
            AnswerKeys.SCHEDULER_BACKEND: self.scheduler_backend,
            # Worker backend selection
            AnswerKeys.WORKER_BACKEND: self.worker_backend,
            # Legacy scheduler persistence flag for backwards compatibility
            AnswerKeys.SCHEDULER_WITH_PERSISTENCE: (
                "yes" if self.scheduler_backend != StorageBackends.MEMORY else "no"
            ),
            # Derived flags for template logic
            "has_background_infrastructure": any(
                c.startswith(ComponentNames.WORKER)
                or c.startswith(ComponentNames.SCHEDULER)
                for c in self.components
            ),
            "needs_redis": ComponentNames.REDIS in self.components,
            # Auth level selection (basic, rbac, or org)
            AnswerKeys.AUTH_LEVEL: (auth_level := self._get_auth_level()),
            # Derived auth level flags for template conditionals
            # Org level implies RBAC (org gets both roles and orgs)
            AnswerKeys.AUTH_RBAC: "yes"
            if auth_level in (AuthLevels.RBAC, AuthLevels.ORG)
            else "no",
            AnswerKeys.AUTH_ORG: "yes" if auth_level == AuthLevels.ORG else "no",
            # OAuth social login (GitHub + Google) — opt-in via the
            # ``auth[oauth]`` modifier in the bracket syntax (composes
            # with ``auth[rbac,oauth]`` etc.). Defaults off so existing
            # flows aren't surprised by extra routes and dependencies.
            AnswerKeys.AUTH_OAUTH: "yes" if self.include_oauth else "no",
            AnswerKeys.PAYMENT_PROVIDER: PaymentProviders.DEFAULT,
            # Insights source flags
            AnswerKeys.INSIGHTS_GITHUB: "yes"
            if "github" in self.insights_sources
            else "no",
            AnswerKeys.INSIGHTS_PYPI: "yes"
            if "pypi" in self.insights_sources
            else "no",
            AnswerKeys.INSIGHTS_PLAUSIBLE: "yes"
            if "plausible" in self.insights_sources
            else "no",
            AnswerKeys.INSIGHTS_REDDIT: "yes"
            if "reddit" in self.insights_sources
            else "no",
            AnswerKeys.INSIGHTS_PER_USER: "yes" if self.insights_per_user else "no",
            # AI backend selection for conversation persistence
            AnswerKeys.AI_BACKEND: self.ai_backend,
            # AI persistence flag for backwards compatibility with template conditionals
            AnswerKeys.AI_WITH_PERSISTENCE: (
                "yes" if self.ai_backend != StorageBackends.MEMORY else "no"
            ),
            # AI framework selection (pydantic-ai or langchain)
            AnswerKeys.AI_FRAMEWORK: self._get_ai_framework(),
            # AI provider selection for dynamic dependency generation
            AnswerKeys.AI_PROVIDERS: self._get_ai_providers_string(),
            # AI RAG (Retrieval-Augmented Generation) selection
            AnswerKeys.AI_RAG: "yes" if self.ai_rag else "no",
            # AI Voice (TTS and STT) selection
            AnswerKeys.AI_VOICE: "yes" if self.ai_voice else "no",
            # Ollama deployment mode (host, docker, or none)
            AnswerKeys.OLLAMA_MODE: self._get_ollama_mode(),
            # Dependency lists for templates
            "selected_components": selected_only,  # Original selection for context
            "docker_services": self._get_docker_services(),
            "pyproject_dependencies": self._get_pyproject_deps(),
        }

    def _get_docker_services(self) -> list[str]:
        """
        Collect all docker services needed.

        Returns:
            List of docker service names
        """
        services = []
        for component_name in self.components:
            if component_name in self.component_specs:
                spec = self.component_specs[component_name]
                if spec.docker_services:
                    services.extend(spec.docker_services)
        return list(dict.fromkeys(services))  # Preserve order, remove duplicates

    def _get_pyproject_deps(self) -> list[str]:
        """
        Collect all Python dependencies.

        Returns:
            Sorted list of Python package dependencies
        """
        deps = []
        # Collect component dependencies
        for component_name in self.components:
            base_name = extract_base_component_name(component_name)
            if base_name in self.component_specs:
                spec = self.component_specs[base_name]
                if spec.pyproject_deps:
                    # Handle worker backend-specific dependencies
                    if base_name == ComponentNames.WORKER:
                        if self.worker_backend == WorkerBackends.TASKIQ:
                            deps.extend(["taskiq>=0.11.11", "taskiq-redis>=1.0.2"])
                        elif self.worker_backend == WorkerBackends.DRAMATIQ:
                            deps.append("dramatiq[redis]>=1.17.0")
                        else:
                            deps.extend(spec.pyproject_deps)  # arq deps from spec
                    # Handle database engine-specific dependencies
                    elif base_name == ComponentNames.DATABASE:
                        deps.extend(["sqlmodel>=0.0.14", "sqlalchemy>=2.0.0"])
                        if self.database_engine == StorageBackends.POSTGRES:
                            deps.extend(["asyncpg>=0.29.0", "psycopg2-binary>=2.9.9"])
                        else:
                            deps.append("aiosqlite>=0.19.0")
                    else:
                        deps.extend(spec.pyproject_deps)

        # Collect service dependencies
        for service_name in self.selected_services:
            # Extract base service name for bracket syntax (e.g., "ai[langchain]" → "ai")
            base_service_name = extract_base_service_name(service_name)
            if base_service_name in SERVICES:
                service_spec = SERVICES[base_service_name]
                if service_spec.pyproject_deps:
                    # Process service dependencies with dynamic substitution
                    for dep in service_spec.pyproject_deps:
                        if (
                            base_service_name == AnswerKeys.SERVICE_AI
                            and "{AI_FRAMEWORK_DEPS}" in dep
                        ):
                            # Substitute AI framework + provider deps dynamically
                            ai_deps = self._get_ai_framework_deps()
                            deps.extend(ai_deps)
                        else:
                            deps.append(dep)

        return sorted(set(deps))  # Sort and deduplicate

    def get_template_files(self) -> list[str]:
        """
        Get list of template files that should be included.

        Returns:
            List of template file paths
        """
        files = []
        # Collect component template files
        for component_name in self.components:
            base_name = extract_base_component_name(component_name)
            if base_name in self.component_specs:
                spec = self.component_specs[base_name]
                if spec.template_files:
                    files.extend(spec.template_files)

        # Collect service template files
        for service in self.selected_services:
            base_service = extract_base_service_name(service)
            if base_service in SERVICES:
                service_spec = SERVICES[base_service]
                if service_spec.template_files:
                    files.extend(service_spec.template_files)

        return list(dict.fromkeys(files))  # Preserve order, remove duplicates

    def _get_ai_providers_string(self) -> str:
        """
        Get AI providers as comma-separated string for pydantic-ai-slim dependency.

        Returns:
            Comma-separated string of provider names (e.g., "openai,anthropic,google")
        """
        # Check if AI service is selected (handle bracket syntax)
        has_ai = any(
            extract_base_service_name(s) == AnswerKeys.SERVICE_AI
            for s in self.selected_services
        )
        if not has_ai:
            # Safe default when the AI service is not selected.
            return AIProviders.OPENAI

        # Import here to avoid circular imports
        from ..cli.interactive import get_ai_provider_selection

        providers = get_ai_provider_selection("ai")
        return ",".join(providers)

    def _get_ai_framework(self) -> str:
        """
        Get AI framework selection (pydantic-ai or langchain).

        Returns:
            Framework name string
        """
        # Check if AI service is selected (handle bracket syntax)
        has_ai = any(
            extract_base_service_name(s) == AnswerKeys.SERVICE_AI
            for s in self.selected_services
        )
        if not has_ai:
            return AIFrameworks.PYDANTIC_AI  # Default

        # Import here to avoid circular imports
        from ..cli.interactive import get_ai_framework_selection

        return get_ai_framework_selection("ai")

    def _get_ollama_mode(self) -> str:
        """
        Get Ollama deployment mode selection (host, docker, or none).

        Returns:
            Ollama mode string
        """
        # Check if AI service is selected (handle bracket syntax)
        has_ai = any(
            extract_base_service_name(s) == AnswerKeys.SERVICE_AI
            for s in self.selected_services
        )
        if not has_ai:
            return OllamaMode.NONE  # Default when AI not selected

        # Import here to avoid circular imports
        from ..cli.interactive import get_ollama_mode_selection

        return get_ollama_mode_selection("ai")

    def _get_auth_level(self) -> str:
        """
        Get auth level selection (basic or rbac).

        Uses the value parsed from bracket syntax in __init__, falling back
        to the interactive global selection.

        Returns:
            Auth level string
        """
        has_auth = any(
            extract_base_service_name(s) == AnswerKeys.SERVICE_AUTH
            for s in self.selected_services
        )
        if not has_auth:
            return AuthLevels.BASIC  # Default

        # If bracket syntax was used, trust the parsed value
        if self._user_specified_auth_level:
            return self.auth_level

        # Fall back to interactive global selection
        from ..cli.interactive import get_auth_level_selection

        return get_auth_level_selection("auth")

    def _get_ai_framework_deps(self) -> list[str]:
        """
        Get AI framework-specific dependencies based on framework and provider selection.

        Returns:
            List of Python package dependency strings
        """
        framework = self._get_ai_framework()
        providers_str = self._get_ai_providers_string()
        providers = providers_str.split(",")

        if framework == AIFrameworks.PYDANTIC_AI:
            # PydanticAI uses a single package with extras
            # Map provider names to pydantic-ai-slim extras
            # Providers using OpenAI-compatible APIs map to "openai" extra
            pydantic_extra_mapping = {
                "public": "openai",  # LLM7.io uses OpenAI-compatible API
                "pollinations": "openai",  # Pollinations uses OpenAI-compatible API
                "openrouter": "openai",  # OpenRouter uses OpenAI-compatible API
                # Future OpenAI-compatible providers go here:
                # "together": "openai",
                # "fireworks": "openai",
            }

            pydantic_extras = []
            for provider in providers:
                provider = provider.strip()
                # Map to the correct extra, or use provider name directly
                extra = pydantic_extra_mapping.get(provider, provider)
                if extra not in pydantic_extras:
                    pydantic_extras.append(extra)

            extras_str = ",".join(pydantic_extras) if pydantic_extras else "openai"
            return [
                f"pydantic-ai-slim[{extras_str}]>=1.0.10",
                "httpx>=0.27.0",  # For API providers
            ]
        else:
            # LangChain uses separate packages per provider
            deps = ["langchain-core>=1.1.0"]

            # Map provider names to LangChain packages
            langchain_packages = {
                "openai": "langchain-openai>=1.1.0",
                "anthropic": "langchain-anthropic>=1.2.0",
                "google": "langchain-google-genai>=4.0.0",
                "groq": "langchain-groq>=1.1.0",
                "mistral": "langchain-mistralai>=1.1.0",
                "cohere": "langchain-cohere>=0.5.0",
            }

            for provider in providers:
                provider = provider.strip()
                if provider in langchain_packages:
                    deps.append(langchain_packages[provider])
                elif (
                    provider in ("public", "pollinations")
                    and "langchain-openai>=1.1.0" not in deps
                ):
                    # Keyless providers use OpenAI-compatible endpoints
                    deps.append("langchain-openai>=1.1.0")

            return deps

    def get_entrypoints(self) -> list[str]:
        """
        Get list of entrypoints that will be created.

        Returns:
            List of entrypoint file paths
        """
        entrypoints = ["app/entrypoints/webserver.py"]  # Always included

        # Check component specs for actual entrypoint files
        for component_name in self.components:
            base_name = extract_base_component_name(component_name)
            if base_name in self.component_specs:
                spec = self.component_specs[base_name]
                if spec.template_files:
                    for template_file in spec.template_files:
                        if (
                            template_file.startswith("app/entrypoints/")
                            and template_file not in entrypoints
                        ):
                            entrypoints.append(template_file)

        return entrypoints

    def get_worker_queues(self) -> list[str]:
        """
        Get list of worker queue files that will be created.

        Returns:
            List of worker queue file paths
        """
        queues: list[str] = []

        # Only check if worker component is included
        if not any(c.startswith(ComponentNames.WORKER) for c in self.components):
            return queues

        # Discover queue files from the template directory
        template_root = (
            Path(__file__).parent.parent / "templates" / "copier-aegis-project"
        )
        worker_queues_dir = (
            template_root
            / "{{ project_slug }}"
            / "app"
            / "components"
            / "worker"
            / "queues"
        )

        if worker_queues_dir.exists():
            for queue_file in worker_queues_dir.glob("*.py"):
                if queue_file.stem == "__init__":
                    continue
                # Filter based on worker backend — each backend has _suffix.py files
                # that get renamed to .py by post_gen_tasks
                is_taskiq_file = queue_file.stem.endswith("_taskiq")
                is_dramatiq_file = queue_file.stem.endswith("_dramatiq")
                is_backend_specific = is_taskiq_file or is_dramatiq_file

                if self.worker_backend == WorkerBackends.TASKIQ:
                    if is_taskiq_file:
                        final_name = queue_file.name.replace("_taskiq.py", ".py")
                        queues.append(f"app/components/worker/queues/{final_name}")
                elif self.worker_backend == WorkerBackends.DRAMATIQ:
                    if is_dramatiq_file:
                        final_name = queue_file.name.replace("_dramatiq.py", ".py")
                        queues.append(f"app/components/worker/queues/{final_name}")
                else:
                    # arq (default): show non-backend-specific files
                    if not is_backend_specific:
                        queues.append(f"app/components/worker/queues/{queue_file.name}")

        return sorted(queues)
