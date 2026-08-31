"""English locale — canonical message definitions for Aegis Stack CLI."""

MESSAGES: dict[str, str] = {
    # ── Validation ─────────────────────────────────────────────────────
    "validation.invalid_name": (
        "Invalid project name. Only letters, numbers, hyphens, "
        "and underscores are allowed."
    ),
    "validation.reserved_name": "'{name}' is a reserved name.",
    "validation.name_too_long": (
        "Project name too long. Maximum 50 characters allowed."
    ),
    "validation.invalid_python": (
        "Invalid Python version '{version}'. Must be one of: {supported}"
    ),
    "validation.unknown_service": "Unknown service: {name}",
    "validation.unknown_services": "Unknown services: {names}",
    "validation.unknown_component": "Unknown component: {name}",
    # ── Init command ───────────────────────────────────────────────────
    "init.title": "Aegis Stack Project Initialization",
    "init.location": "Location:",
    "init.template_version": "Template Version:",
    "init.dir_exists": "Directory '{path}' already exists",
    "init.dir_exists_hint": "Use --force to overwrite or choose a different name",
    "init.overwriting": "Overwriting existing directory: {path}",
    "init.services_require": "Services require components: {components}",
    "init.compat_errors": "Service-component compatibility errors:",
    "init.suggestion_add": (
        "Suggestion: Add missing components --components {components}"
    ),
    "init.suggestion_remove": (
        "Or remove --components to let services auto-add dependencies."
    ),
    "init.suggestion_interactive": (
        "Alternatively, use interactive mode to auto-add service dependencies."
    ),
    "init.auto_detected_scheduler": (
        "Auto-detected: Scheduler with {backend} persistence"
    ),
    "init.auto_added_deps": "Auto-added dependencies: {deps}",
    "init.auto_added_by_services": "Auto-added by services:",
    "init.required_by": "required by {services}",
    "init.config_title": "Project Configuration",
    "init.config_name": "Name:",
    "init.config_core": "Core:",
    "init.config_infra": "Infrastructure:",
    "init.config_web_frontend": "Web frontend:",
    "init.config_services": "Services:",
    "init.component_files": "Component Files:",
    "init.entrypoints": "Entrypoints:",
    "init.worker_queues": "Worker Queues:",
    "init.dependencies": "Dependencies to be installed:",
    "init.confirm_create": "Create this project?",
    "init.cancelled": "Project creation cancelled",
    "init.removing_dir": "Removing existing directory: {path}",
    "init.creating": "Creating project: {name}",
    "init.error": "Error creating project: {error}",
    "init.replay_hint": "Recreate this stack anytime:",
    # ── Interactive: section headers ───────────────────────────────────
    "interactive.component_selection": "Component Selection",
    "interactive.service_selection": "Service Selection",
    "interactive.core_included": (
        "Core components ({components}) included automatically"
    ),
    "interactive.infra_header": "Infrastructure Components:",
    "interactive.services_intro": (
        "Services provide business logic functionality for your application."
    ),
    # ── Component descriptions ──────────────────────────────────────────
    "component.backend": "FastAPI backend server",
    "component.frontend": "Flet frontend interface",
    "component.redis": "Redis cache and message broker",
    "component.worker": "Background task processing (arq, Dramatiq, or TaskIQ)",
    "component.scheduler": "Scheduled task execution infrastructure",
    "component.database": "Database with SQLModel ORM (SQLite or PostgreSQL)",
    "component.ingress": "Traefik reverse proxy and load balancer",
    "component.observability": "Logfire observability, tracing, and metrics",
    "component.htmx": "Server-rendered htmx web frontend",
    # ── Service descriptions ────────────────────────────────────────────
    "service.auth": "User authentication and authorization with JWT tokens",
    "service.ai": "AI chatbot service with multi-framework support",
    "service.comms": "Communications service with email, SMS and voice",
    "service.blog": "Markdown blog with draft/publish workflow and tags",
    # ── Interactive: component prompts ─────────────────────────────────
    "interactive.add_prompt": "Add {description}?",
    "interactive.add_with_redis": "Add {description}? (will auto-add Redis)",
    "interactive.worker_configured": "Worker with {backend} backend configured",
    # ── Interactive: scheduler ─────────────────────────────────────────
    "interactive.scheduler_persistence": "Scheduler Persistence:",
    "interactive.persist_prompt": (
        "Do you want to persist scheduled jobs? "
        "(Enables job history, recovery after restarts)"
    ),
    "interactive.scheduler_db_configured": ("Scheduler + {engine} database configured"),
    "interactive.bonus_backup": "Bonus: Adding database backup job",
    "interactive.backup_desc": (
        "Scheduled daily database backup job included (runs at 2 AM)"
    ),
    # ── Interactive: database engine ───────────────────────────────────
    "interactive.db_engine_label": "{context} Database Engine:",
    "interactive.db_select": "Select database engine:",
    "interactive.db_sqlite": "SQLite - Simple, file-based (good for development)",
    "interactive.db_postgres": (
        "PostgreSQL - Production-ready, multi-container support"
    ),
    "interactive.db_reuse": "Using previously selected database: {engine}",
    # ── Interactive: PostgreSQL host (provider) ────────────────────────
    "interactive.db_provider_select": "Select PostgreSQL host:",
    "interactive.db_provider_container": (
        "Local container - postgres:16 in Docker (dev and prod)"
    ),
    "interactive.db_provider_neon": (
        "Neon - serverless Postgres (cloud in prod, local container in dev)"
    ),
    # ── Interactive: worker backend ────────────────────────────────────
    "interactive.worker_label": "Worker Backend:",
    "interactive.worker_select": "Select worker backend:",
    "interactive.worker_arq": "arq - Async, lightweight (default)",
    "interactive.worker_dramatiq": (
        "Dramatiq - Process-based, ideal for CPU-bound work"
    ),
    "interactive.worker_taskiq": (
        "TaskIQ - Async, framework-style with per-queue brokers"
    ),
    # ── Interactive: auth ──────────────────────────────────────────────
    "interactive.auth_header": "Authentication Services:",
    "interactive.auth_level_label": "Authentication Level:",
    "interactive.auth_select": "What type of authentication?",
    "interactive.auth_basic": "Basic - Email/password login",
    "interactive.auth_rbac": "With Roles - + role-based access control (experimental)",
    "interactive.auth_org": "With Organizations - + multi-tenant support (experimental)",
    "interactive.auth_selected": "Selected auth level: {level}",
    "interactive.auth_db_required": "Database Required:",
    "interactive.auth_db_reason": (
        "Authentication requires a database for user storage"
    ),
    "interactive.auth_db_details": "(user accounts, sessions, JWT tokens)",
    "interactive.auth_db_already": "Database component already selected",
    "interactive.auth_db_confirm": "Continue and add database component?",
    "interactive.auth_cancelled": "Authentication service cancelled",
    "interactive.auth_db_configured": "Authentication + Database configured",
    # ── Interactive: AI service ────────────────────────────────────────
    "interactive.ai_header": "AI & Machine Learning Services:",
    "interactive.ai_framework_label": "AI Framework Selection:",
    "interactive.ai_framework_intro": "Choose your AI framework:",
    "interactive.ai_pydanticai": (
        "PydanticAI - Type-safe, Pythonic AI framework (recommended)"
    ),
    "interactive.ai_langchain": (
        "LangChain - Popular framework with extensive integrations"
    ),
    "interactive.ai_use_pydanticai": "Use PydanticAI? (recommended)",
    "interactive.ai_selected_framework": "Selected framework: {framework}",
    "interactive.ai_tracking_context": "AI Usage Tracking",
    "interactive.ai_tracking_label": "LLM Usage Tracking:",
    "interactive.ai_tracking_prompt": (
        "Enable usage tracking? (token counts, costs, conversation history)"
    ),
    "interactive.ai_sync_label": "LLM Catalog Sync:",
    "interactive.ai_sync_desc": (
        "Syncing fetches latest model data from OpenRouter/LiteLLM APIs"
    ),
    "interactive.ai_sync_time": (
        "This requires network access and takes ~30-60 seconds"
    ),
    "interactive.ai_sync_prompt": ("Sync LLM catalog during project generation?"),
    "interactive.ai_sync_will": ("LLM catalog will be synced after project generation"),
    "interactive.ai_sync_skipped": (
        "LLM sync skipped - static fixture data will be available"
    ),
    "interactive.ai_provider_label": "AI Provider Selection:",
    "interactive.ai_provider_intro": (
        "Choose AI providers to include (multiple selection supported)"
    ),
    "interactive.ai_provider_options": "Provider Options:",
    "interactive.ai_provider_recommended": "(Recommended)",
    "interactive.ai_provider.public": "LLM7.io - Free public endpoint (No API key)",
    "interactive.ai_provider.openai": "OpenAI - GPT models (Paid)",
    "interactive.ai_provider.anthropic": "Anthropic - Claude models (Paid)",
    "interactive.ai_provider.google": "Google - Gemini models (Free tier, Flash only)",
    "interactive.ai_provider.groq": "Groq - Fast inference (Free tier)",
    "interactive.ai_provider.mistral": "Mistral - Open models (Mostly paid)",
    "interactive.ai_provider.cohere": "Cohere - Enterprise focus (Limited free)",
    "interactive.ai_provider.ollama": "Ollama - Local inference (Free)",
    "interactive.ai_no_providers": (
        "No providers selected, adding recommended defaults..."
    ),
    "interactive.ai_selected_providers": "Selected providers: {providers}",
    "interactive.ai_deps_optimized": (
        "Dependencies will be optimized for your selection"
    ),
    "interactive.ai_ollama_label": "Ollama Deployment Mode:",
    "interactive.ai_ollama_intro": "How do you want to run Ollama?",
    "interactive.ai_ollama_host": (
        "Host - Connect to Ollama running on your machine (Mac/Windows)"
    ),
    "interactive.ai_ollama_docker": (
        "Docker - Run Ollama in a Docker container (Linux/Deploy)"
    ),
    "interactive.ai_ollama_host_prompt": (
        "Connect to host Ollama? (recommended for Mac/Windows)"
    ),
    "interactive.ai_ollama_host_ok": (
        "Ollama will connect to host.docker.internal:11434"
    ),
    "interactive.ai_ollama_host_hint": ("Make sure Ollama is running: ollama serve"),
    "interactive.ai_ollama_docker_ok": (
        "Ollama service will be added to docker-compose.yml"
    ),
    "interactive.ai_ollama_docker_hint": (
        "Note: First startup may take time to download models"
    ),
    "interactive.ai_rag_label": "RAG (Retrieval-Augmented Generation):",
    "interactive.ai_rag_prompt": (
        "Enable RAG for document indexing and semantic search?"
    ),
    "interactive.ai_rag_enabled": "RAG enabled with ChromaDB vector store",
    "interactive.ai_voice_label": "Voice (Text-to-Speech & Speech-to-Text):",
    "interactive.ai_voice_prompt": (
        "Enable voice capabilities? (TTS and STT for voice interactions)"
    ),
    "interactive.ai_voice_enabled": "Voice enabled with TTS and STT support",
    "interactive.ai_db_already": ("Database already selected - usage tracking enabled"),
    "interactive.ai_db_added": ("Database ({backend}) added for usage tracking"),
    "interactive.ai_configured": "AI service configured",
    # ── Shared: validation ──────────────────────────────────────────────
    "shared.not_copier_project": ("Project at {path} was not generated with Copier."),
    "shared.copier_only": (
        "The 'aegis {command}' command only works with Copier-generated projects."
    ),
    "shared.regenerate_hint": (
        "To add components, regenerate the project with the new components included."
    ),
    "shared.git_not_initialized": "Project is not in a git repository",
    "shared.git_required": "Copier updates require git for change tracking",
    "shared.git_init_hint": (
        "Projects created with 'aegis init' should have git initialized automatically"
    ),
    "shared.git_manual_init": (
        "If you created this project manually, run: "
        "git init && git add . && git commit -m 'Initial commit'"
    ),
    "shared.empty_component": "Empty component name is not allowed",
    "shared.empty_service": "Empty service name is not allowed",
    # ── Shared: next steps / review ──────────────────────────────────
    "shared.next_steps": "Next steps:",
    "shared.next_make_check": "   1. Run 'make check' to verify the update",
    "shared.next_test": "   2. Test your application",
    "shared.next_commit": "   3. Commit the changes with: git add . && git commit",
    "shared.review_header": "Review changes:",
    "shared.review_docker": "   git diff docker-compose.yml",
    "shared.review_pyproject": "   git diff pyproject.toml",
    "shared.operation_cancelled": "Operation cancelled",
    "shared.interactive_ignores_args": (
        "Warning: --interactive flag ignores component arguments"
    ),
    "shared.no_components_selected": "No components selected",
    "shared.no_services_selected": "No services selected",
    # ── Add command ──────────────────────────────────────────────────
    "add.title": "Aegis Stack - Add Components",
    "add.project": "Project: {path}",
    "add.error_no_args": (
        "Error: components argument is required (or use --interactive)"
    ),
    "add.usage_hint": "Usage: aegis add scheduler,worker",
    "add.interactive_hint": "Or: aegis add --interactive",
    "add.auto_added_deps": "Auto-added dependencies: {deps}",
    "add.validation_failed": "Component validation failed: {error}",
    "add.load_config_failed": "Failed to load project configuration: {error}",
    "add.already_enabled": "Already enabled: {components}",
    "add.all_enabled": "All requested components are already enabled!",
    "add.components_to_add": "Components to add:",
    "add.scheduler_backend": "Scheduler backend: {backend}",
    "add.confirm": "Add these components?",
    "add.updating": "Updating project...",
    "add.adding": "Adding {component}...",
    "add.added_files": "Added {count} files",
    "add.skipped_files": "Skipped {count} existing files",
    "add.success": "Components added successfully!",
    "add.failed_component": "Failed to add {component}: {error}",
    "add.failed": "Failed to add components: {error}",
    "add.plugin_installing": "Installing plugin: {name}",
    "add.plugin_confirm": "Add plugin {name} to this project?",
    "add.plugin_success": "Plugin {name} installed.",
    "add.invalid_format": "Invalid component format: {error}",
    "add.bracket_override": (
        "Bracket syntax 'scheduler[{engine}]' overrides --backend {backend}"
    ),
    "add.invalid_scheduler_backend": ("Invalid scheduler backend: '{backend}'"),
    "add.invalid_worker_backend": "Invalid worker backend: '{backend}'",
    "add.valid_backends": "Valid options: {options}",
    "add.postgres_coming": "Note: PostgreSQL support coming in future release",
    "add.auto_added_db": ("Auto-added database component for scheduler persistence"),
    "add.generated_migration": "Generated migration: {name}",
    "add.scheduler_db_engine_mismatch": (
        "Cannot use scheduler backend '{backend}': the project's database "
        "engine is '{engine}'. They must match."
    ),
    # ── Remove command ────────────────────────────────────────────────
    "remove.title": "Aegis Stack - Remove Components",
    "remove.project": "Project: {path}",
    "remove.error_no_args": (
        "Error: components argument is required (or use --interactive)"
    ),
    "remove.usage_hint": "Usage: aegis remove scheduler,worker",
    "remove.interactive_hint": "Or: aegis remove --interactive",
    "remove.no_selected": "No components selected for removal",
    "remove.validation_failed": "Component validation failed: {error}",
    "remove.load_config_failed": "Failed to load project configuration: {error}",
    "remove.cannot_remove_core": "Cannot remove core component: {component}",
    "remove.not_enabled": "Not enabled: {components}",
    "remove.nothing_to_remove": "No components to remove!",
    "remove.auto_remove_redis": (
        "Auto-removing redis (no standalone functionality, only used by worker)"
    ),
    "remove.scheduler_persistence_warn": "IMPORTANT: Scheduler Persistence Warning",
    "remove.scheduler_persistence_detail": (
        "Your scheduler uses SQLite for job persistence."
    ),
    "remove.scheduler_db_remains": (
        "The database file at data/scheduler.db will remain."
    ),
    "remove.scheduler_keep_hint": (
        "To keep your job history: Leave the database component"
    ),
    "remove.scheduler_remove_hint": (
        "To remove all data: Also remove the database component"
    ),
    "remove.components_to_remove": "Components to remove:",
    "remove.warning_delete": (
        "WARNING: This will DELETE component files from your project!"
    ),
    "remove.commit_hint": "Make sure you have committed your changes to git.",
    "remove.confirm": "Remove these components?",
    "remove.removing_all": "Removing components...",
    "remove.removing": "Removing {component}...",
    "remove.removed_files": "Removed {count} files",
    "remove.failed_component": "Failed to remove {component}: {error}",
    "remove.success": "Components removed successfully!",
    "remove.failed": "Failed to remove components: {error}",
    "remove.plugin_removing": "Removing plugin: {name}",
    "remove.plugin_confirm": "Remove plugin {name} from this project?",
    "remove.plugin_success": "Plugin {name} removed.",
    # ── Manual updater ─────────────────────────────────────────────────
    "updater.processing_files": "Processing {count} component files...",
    "updater.updating_shared": "Updating shared template files...",
    "updater.shared_preserved": "Preserved local changes (skipped regen, merge manually): {file}",
    "updater.shared_merged": "Merged template changes into your customized file: {file}",
    "updater.shared_conflict": "Merge conflict (markers written, resolve manually): {file}",
    "updater.running_postgen": "Running post-generation tasks...",
    "updater.deps_synced": "Dependencies synced (uv sync)",
    "updater.code_formatted": "Code formatted (make fix)",
    # ── Project map ──────────────────────────────────────────────────
    "projectmap.new": "NEW",
    # ── Post-generation: setup tasks ──────────────────────────────────
    "postgen.setup_start": "Setting up your project environment...",
    "postgen.deps_installing": "Installing dependencies with uv...",
    "postgen.deps_success": "Dependencies installed successfully",
    "postgen.deps_failed": "Project generation failed: dependency installation failed",
    "postgen.deps_failed_detail": (
        "The generated project files remain in place, but the project is not usable."
    ),
    "postgen.deps_failed_hint": (
        "Fix the dependency issue (check Python version compatibility) and try again."
    ),
    "postgen.deps_warn_failed": "Warning: Dependency installation failed",
    "postgen.deps_manual": "Run 'uv sync' manually after project creation",
    "postgen.deps_timeout": (
        "Warning: Dependency installation timeout - run 'uv sync' manually"
    ),
    "postgen.deps_uv_missing": "Warning: uv not found in PATH",
    "postgen.deps_uv_install": "Install uv first: https://github.com/astral-sh/uv",
    "postgen.deps_warn_error": "Warning: Dependency installation failed: {error}",
    "postgen.env_setup": "Setting up environment configuration...",
    "postgen.env_created": "Environment file created from .env.example",
    "postgen.env_exists": "Environment file already exists",
    "postgen.env_missing": "Warning: No .env.example file found",
    "postgen.env_error": "Warning: Environment setup failed: {error}",
    "postgen.env_manual": "Copy .env.example to .env manually",
    # ── Post-generation: database/migrations ────────────────────────────
    "postgen.db_setup": "Setting up database schema...",
    "postgen.db_success": "Database tables created successfully",
    "postgen.db_alembic_missing": "Warning: Alembic config file not found at {path}",
    "postgen.db_alembic_hint": (
        "Skipping database migration. Please ensure the config file exists "
        "and run 'alembic upgrade head' manually."
    ),
    "postgen.db_failed": "Warning: Database migration setup failed",
    "postgen.db_manual": "Run 'alembic upgrade head' manually after project creation",
    "postgen.db_timeout": (
        "Warning: Migration setup timeout - run 'alembic upgrade head' manually"
    ),
    "postgen.db_error": "Warning: Migration setup failed: {error}",
    # ── Post-generation: LLM fixtures/sync ────────────────────────────
    "postgen.llm_seeding": "Seeding LLM fixtures...",
    "postgen.llm_seed_success": "LLM fixtures seeded successfully",
    "postgen.llm_seed_failed": "Warning: LLM fixture seeding failed",
    "postgen.llm_seed_manual": (
        "You can seed fixtures manually by running the fixture loader"
    ),
    "postgen.llm_seed_timeout": "Warning: LLM fixture seeding timeout",
    "postgen.llm_seed_error": "Warning: LLM fixture seeding failed: {error}",
    "postgen.llm_syncing": "Syncing LLM catalog from external APIs...",
    "postgen.llm_sync_success": "LLM catalog synced successfully",
    "postgen.llm_sync_failed": "Warning: LLM catalog sync failed",
    "postgen.llm_sync_manual": (
        "Run '{slug} llm sync' manually to populate the catalog"
    ),
    "postgen.llm_sync_timeout": "Warning: LLM catalog sync timeout",
    "postgen.llm_sync_error": "Warning: LLM catalog sync failed: {error}",
    # ── Post-generation: formatting ───────────────────────────────────
    "postgen.format_timeout": (
        "Warning: Formatting timeout - run 'make fix' manually when ready"
    ),
    "postgen.format_error": "Warning: Auto-formatting skipped: {error}",
    "postgen.format_error_manual": "Run 'make fix' manually to format code",
    "postgen.format_start": "Auto-formatting generated code...",
    "postgen.format_success": "Code formatting completed successfully",
    "postgen.format_partial": (
        "Some formatting issues detected, but project created successfully"
    ),
    "postgen.format_manual": "Run 'make fix' manually to resolve remaining issues",
    "postgen.format_hint": "Run 'make fix' to format code when ready",
    "postgen.llm_sync_skipped": "LLM catalog sync skipped",
    "postgen.llm_fixtures_outdated": "Static fixture data loaded (may be outdated)",
    "postgen.llm_sync_hint": "Run '{slug} llm sync' later to get latest model data",
    "postgen.llm_fixtures_fallback": (
        "Static fixture data is available but may be outdated"
    ),
    "postgen.ready": "Project ready to run!",
    "postgen.next_steps": "Next steps:",
    "postgen.next_cd": "   cd {path}",
    "postgen.next_serve": "   make serve",
    "postgen.next_dashboard": "   Open Overseer: http://localhost:8000/dashboard/",
    # ── Post-generation: project map ──────────────────────────────────
    "projectmap.title": "Project Structure:",
    "projectmap.components": "Components",
    "projectmap.services": "Business logic",
    "projectmap.models": "Database models",
    "projectmap.cli": "CLI commands",
    "projectmap.entrypoints": "Run targets",
    "projectmap.tests": "Test suite",
    "projectmap.migrations": "Migrations",
    "projectmap.auth": "Authentication",
    "projectmap.ai": "AI conversations",
    "projectmap.comms": "Communications",
    "projectmap.insights": "Adoption metrics",
    "projectmap.payment": "Payments and subscriptions",
    "projectmap.blog": "Markdown blog",
    "projectmap.finance": "Personal finance",
    "projectmap.docs": "Documentation",
    # ── Post-generation: footer ───────────────────────────────────────
    "postgen.docs_link": "Docs: https://docs.aegis-stack.io",
    "postgen.star_prompt": (
        "If Aegis Stack made your life easier, consider leaving a star:"
    ),
    # ── Add-service command ────────────────────────────────────────────
    "add_service.title": "Aegis Stack - Add Services",
    "add_service.project": "Project: {path}",
    "add_service.error_no_args": (
        "Error: services argument is required (or use --interactive)"
    ),
    "add_service.usage_hint": "Usage: aegis add-service auth,ai",
    "add_service.interactive_hint": "Or: aegis add-service --interactive",
    "add_service.interactive_ignores_args": (
        "Warning: --interactive flag ignores service arguments"
    ),
    "add_service.no_selected": "No services selected",
    "add_service.already_enabled": "Already enabled: {services}",
    "add_service.all_enabled": "All requested services are already enabled!",
    "add_service.validation_failed": "Service validation failed: {error}",
    "add_service.load_config_failed": ("Failed to load project configuration: {error}"),
    "add_service.services_to_add": "Services to add:",
    "add_service.required_components": ("Required components (will be auto-added):"),
    "add_service.already_have_components": (
        "Already have required components: {components}"
    ),
    "add_service.confirm": "Add these services?",
    "add_service.adding_component": ("Adding required component: {component}..."),
    "add_service.failed_component": ("Failed to add component {component}: {error}"),
    "add_service.added_files": "Added {count} files",
    "add_service.skipped_files": "Skipped {count} existing files",
    "add_service.preserved_files": "{count} shared file(s) need manual review (see messages above)",
    "add_service.adding_service": "Adding service: {service}...",
    "add_service.failed_service": ("Failed to add service {service}: {error}"),
    "add_service.resolve_failed": ("Failed to resolve service dependencies: {error}"),
    "add_service.bootstrap_alembic": "Bootstrapping alembic infrastructure...",
    "add_service.created_file": "Created: {file}",
    "add_service.generated_migration": "Generated migration: {name}",
    "add_service.applying_migrations": "Applying database migrations...",
    "add_service.migration_failed": (
        "Warning: Auto-migration failed. Run 'make migrate' manually."
    ),
    "add_service.success": "Services added successfully!",
    "add_service.failed": "Failed to add services: {error}",
    "add_service.auth_setup": "Auth Service Setup:",
    "add_service.auth_create_users": "   1. Create test users: {cmd}",
    "add_service.auth_view_routes": "   2. View auth routes: {url}",
    "add_service.ai_setup": "AI Service Setup:",
    "add_service.ai_set_provider": (
        "   1. Set {env_var} in .env (openai, anthropic, google, groq)"
    ),
    "add_service.ai_set_api_key": ("   2. Set provider API key ({env_var}, etc.)"),
    "add_service.ai_test_cli": "   3. Test with CLI: {cmd}",
    # ── Remove-service command ─────────────────────────────────────────
    "remove_service.title": "Aegis Stack - Remove Services",
    "remove_service.project": "Project: {path}",
    "remove_service.error_no_args": (
        "Error: services argument is required (or use --interactive)"
    ),
    "remove_service.usage_hint": "Usage: aegis remove-service auth,ai",
    "remove_service.interactive_hint": "Or: aegis remove-service --interactive",
    "remove_service.interactive_ignores_args": (
        "Warning: --interactive flag ignores service arguments"
    ),
    "remove_service.no_selected": "No services selected for removal",
    "remove_service.not_enabled": "Not enabled: {services}",
    "remove_service.nothing_to_remove": "No services to remove!",
    "remove_service.validation_failed": "Service validation failed: {error}",
    "remove_service.load_config_failed": (
        "Failed to load project configuration: {error}"
    ),
    "remove_service.services_to_remove": "Services to remove:",
    "remove_service.auth_warning": "IMPORTANT: Auth Service Warning",
    "remove_service.auth_delete_intro": "Removing auth service will delete:",
    "remove_service.auth_delete_endpoints": ("User authentication API endpoints"),
    "remove_service.auth_delete_models": ("User model and authentication services"),
    "remove_service.auth_delete_jwt": "JWT token handling code",
    "remove_service.auth_db_note": (
        "Note: Database tables and alembic migrations are NOT deleted."
    ),
    "remove_service.warning_delete": (
        "WARNING: This will DELETE service files from your project!"
    ),
    "remove_service.confirm": "Remove these services?",
    "remove_service.removing": "Removing service: {service}...",
    "remove_service.failed_service": ("Failed to remove service {service}: {error}"),
    "remove_service.removed_files": "Removed {count} files",
    "remove_service.success": "Services removed successfully!",
    "remove_service.failed": "Failed to remove services: {error}",
    "remove_service.deps_not_removed": (
        "Note: Service dependencies (database, etc.) were NOT removed."
    ),
    "remove_service.deps_remove_hint": (
        "Use 'aegis remove <component>' to remove components separately."
    ),
    # ── Version command ────────────────────────────────────────────────
    "version.info": "Aegis Stack CLI v{version}",
    # ── Components command ─────────────────────────────────────────────
    "components.core_title": "CORE COMPONENTS",
    "components.backend_desc": (
        "  backend      - FastAPI backend server (always included)"
    ),
    "components.frontend_desc": (
        "  frontend     - Flet frontend interface (always included)"
    ),
    "components.infra_title": "INFRASTRUCTURE COMPONENTS",
    "components.frontend_title": "FRONTEND COMPONENTS",
    "components.requires": "Requires: {deps}",
    "components.recommends": "Recommends: {deps}",
    "components.usage_hint": (
        "Use 'aegis init PROJECT_NAME --components redis,worker' to select components"
    ),
    # ── Services command ───────────────────────────────────────────────
    "services.title": "AVAILABLE SERVICES",
    "services.type_auth": "Authentication Services",
    "services.type_payment": "Payment Services",
    "services.type_ai": "AI & Machine Learning Services",
    "services.type_notification": "Notification Services",
    "services.type_analytics": "Analytics Services",
    "services.type_storage": "Storage Services",
    "services.type_content": "Content Services",
    "services.type_finance": "Finance Services",
    "services.requires_components": "Requires components: {deps}",
    "services.recommends_components": "Recommends components: {deps}",
    "services.requires_services": "Requires services: {deps}",
    "services.none_available": "  No services available yet.",
    "services.usage_hint": (
        "Use 'aegis init PROJECT_NAME --services auth' to add services"
    ),
    # ── Update command ─────────────────────────────────────────────────
    "update.title": "Aegis Stack - Update Template",
    "update.not_copier": ("Project at {path} was not generated with Copier."),
    "update.copier_only": (
        "The 'aegis update' command only works with Copier-generated projects."
    ),
    "update.need_regen": ("Projects generated before v0.2.0 need to be regenerated."),
    "update.project": "Project: {path}",
    "update.commit_or_stash": (
        "Commit or stash your changes before running 'aegis update'."
    ),
    "update.clean_required": (
        "Copier requires a clean git tree to safely merge changes."
    ),
    "update.git_clean": "Git tree is clean",
    "update.dirty_tree": "Git tree has uncommitted changes",
    "update.changelog_breaking": "Breaking Changes:",
    "update.changelog_features": "New Features:",
    "update.changelog_fixes": "Bug Fixes:",
    "update.changelog_other": "Other Changes:",
    "update.current_commit": "   Current: {commit}...",
    "update.target_commit": "   Target:  {commit}...",
    "update.unknown_version": ("Warning: Cannot determine current template version"),
    "update.untagged_commit": (
        "Project may have been generated from an untagged commit"
    ),
    "update.custom_template": "Using custom template ({source}): {path}",
    "update.version_info": "Version Information:",
    "update.current_cli": "   Current CLI:      {version}",
    "update.current_template": "   Current Template: {version}",
    "update.current_template_commit": ("   Current Template: {commit}... (commit)"),
    "update.current_template_unknown": "   Current Template: unknown",
    "update.target_template": "   Target Template:  {version}",
    "update.already_at_version": ("Project is already at the requested version"),
    "update.already_at_commit": "Project is already at the target commit",
    "update.ahead_of_target": ("Project is newer than the target template version"),
    "update.ahead_of_target_hint": (
        "Nothing to update. Use --to-version to target a specific version."
    ),
    "update.downgrade_blocked": "Downgrade not supported",
    "update.downgrade_reason": (
        "Copier does not support downgrading to older template versions."
    ),
    "update.changelog": "Changelog:",
    "update.dry_run": "DRY RUN MODE - No changes will be applied",
    "update.dry_run_hint": "To apply this update, run:",
    "update.confirm": "Apply this update?",
    "update.cancelled": "Update cancelled",
    "update.creating_backup": "Creating backup point...",
    "update.backup_created": "   Backup created: {tag}",
    "update.backup_failed": "Could not create backup point",
    "update.updating": "Updating project...",
    "update.updating_to": "Updating to template version {version}",
    "update.moved_files": ("   Moved {count} new files from nested directory"),
    "update.synced_files": "   Synced {count} template changes",
    "update.merge_conflicts": (
        "   {count} file(s) have merge conflicts (search for <<<<<<< to resolve):"
    ),
    "update.removed_files": "   Removed {count} file(s) the template no longer ships",
    "update.stale_files": (
        "   {count} customized file(s) are no longer part of the template.\n"
        "   They were kept, but nothing loads them any more - review and delete:"
    ),
    "update.running_postgen": "Running post-generation tasks...",
    "update.skipping_postgen_conflicts": (
        "Skipping post-generation tasks — merge conflicts present.\n"
        "   Resolve <<<<<<< markers, then run: uv sync && make check"
    ),
    "update.version_updated": ("   Updated __aegis_version__ to {version}"),
    "update.success": "Update completed successfully!",
    "update.partial_success": (
        "Update completed with some post-generation task failures"
    ),
    "update.partial_detail": ("   Some setup tasks failed. See details above."),
    "update.next_steps": "Next Steps:",
    "update.next_review": "   1. Review changes: git diff",
    "update.next_conflicts": "   2. Check for conflicts (*.rej files)",
    "update.next_test": "   3. Run tests: make check",
    "update.next_commit": ("   4. Commit changes: git add . && git commit"),
    "update.failed": "Update failed: {error}",
    "update.rollback_prompt": "Rollback to previous state?",
    "update.manual_rollback": "Manual rollback: git reset --hard {tag}",
    "update.troubleshooting": "Troubleshooting:",
    "update.troubleshoot_clean": ("   - Ensure you have a clean git tree"),
    "update.troubleshoot_version": ("   - Check that the version/commit exists"),
    "update.troubleshoot_docs": ("   - Review Copier documentation for update issues"),
    # ── Ingress command ────────────────────────────────────────────────
    "ingress.title": "Aegis Stack - Enable Ingress TLS",
    "ingress.project": "Project: {path}",
    "ingress.not_found": ("Ingress component not found. Adding it first..."),
    "ingress.add_confirm": "Add the ingress component?",
    "ingress.add_failed": ("Failed to add ingress component: {error}"),
    "ingress.added": "Ingress component added.",
    "ingress.tls_already": "TLS is already enabled on this project.",
    "ingress.domain_label": "   Domain: {domain}",
    "ingress.acme_email": "   ACME email: {email}",
    "ingress.domain_prompt": (
        "Domain name (e.g., example.com, or empty for IP-based routing)"
    ),
    "ingress.email_reuse": "Using existing email for ACME: {email}",
    "ingress.email_prompt": "Email for Let's Encrypt notifications",
    "ingress.email_required": (
        "Error: --email is required for TLS (needed for Let's Encrypt)"
    ),
    "ingress.tls_config": "TLS Configuration:",
    "ingress.domain_none": ("   Domain: (none - IP/PathPrefix routing)"),
    "ingress.tls_confirm": "Enable TLS with this configuration?",
    "ingress.enabling": "Enabling TLS...",
    "ingress.updated_file": "   Updated: {file}",
    "ingress.created_file": "   Created: {file}",
    "ingress.success": "TLS enabled successfully!",
    "ingress.available_at": ("   Your app will be available at: https://{domain}"),
    "ingress.https_configured": ("   HTTPS is now configured with Let's Encrypt"),
    "ingress.next_steps": "Next steps:",
    "ingress.next_deploy": "   1. Deploy with: aegis deploy",
    "ingress.next_ports": ("   2. Ensure ports 80 and 443 are open on your server"),
    "ingress.next_dns": (
        "   3. Point your DNS A record for {domain} to your server IP"
    ),
    "ingress.next_certs": ("   Certificates will be auto-provisioned on first request"),
    # ── Deploy commands ────────────────────────────────────────────────
    "deploy.no_config": (
        "No deploy configuration found. Run 'aegis deploy-init' first."
    ),
    "deploy.init_saved": ("Deploy configuration saved to {file}"),
    "deploy.init_host": "   Host: {host}",
    "deploy.init_user": "   User: {user}",
    "deploy.init_path": "   Path: {path}",
    "deploy.init_docker_context": "   Docker Context: {context}",
    "deploy.prompt_host": "Server IP or hostname",
    "deploy.init_gitignore": (
        "Note: Consider adding .aegis/ to .gitignore to avoid committing deploy config"
    ),
    "deploy.setup_title": "Setting up server at {target}...",
    "deploy.checking_ssh": "Checking SSH connectivity...",
    "deploy.adding_host_key": "Adding server to known_hosts...",
    "deploy.ssh_keyscan_failed": ("Failed to scan SSH host key: {error}"),
    "deploy.ssh_failed": "SSH connection failed: {error}",
    "deploy.copying_script": "Copying setup script to server...",
    "deploy.copy_failed": "Failed to copy setup script",
    "deploy.running_setup": ("Running server setup (this may take a few minutes)..."),
    "deploy.setup_failed": "Server setup failed",
    "deploy.setup_script_missing": ("Server setup script not found: {path}"),
    "deploy.setup_script_hint": (
        "Make sure your project was created with the ingress component."
    ),
    "deploy.setup_complete": "Server setup complete!",
    "deploy.setup_verify": "Verifying installation:",
    "deploy.setup_verify_docker": "  Docker: {version}",
    "deploy.setup_verify_compose": "  Docker Compose: {version}",
    "deploy.setup_verify_uv": "  uv: {version}",
    "deploy.setup_verify_app_dir": "  App Directory: {path}",
    "deploy.setup_next": ("Next: Run 'aegis deploy' to deploy your application"),
    # ── deploy-setup --public-key ──
    "deploy.pubkey_missing": "Public key file not found: {path}",
    "deploy.installing_pubkey": (
        "Installing public key into {user}'s authorized_keys..."
    ),
    "deploy.pubkey_install_failed": "Failed to install public key: {error}",
    "deploy.pubkey_installed": "  Public key installed",
    # ── deploy-cd-setup ──
    "deploy.cd_gh_not_installed": (
        "GitHub CLI (gh) is not installed. Install it from https://cli.github.com/"
    ),
    "deploy.cd_gh_not_authed": (
        "GitHub CLI is not authenticated. Run 'gh auth login' first."
    ),
    "deploy.cd_repo_not_detected": (
        "Could not detect GitHub repo from 'git remote get-url origin'. "
        "Pass --repo OWNER/NAME explicitly."
    ),
    "deploy.cd_already_configured": (
        "CD is already configured for this project (key fingerprint: "
        "{fingerprint}). Use --force to rotate."
    ),
    "deploy.cd_secret_exists": (
        "GitHub Actions secrets already exist: {names}. Use --force to overwrite."
    ),
    "deploy.cd_workflow_exists": (
        "Workflow already exists at {path}. Use --force to overwrite."
    ),
    "deploy.cd_title": ("Setting up GitHub Actions CD for {repo} → {target}..."),
    "deploy.cd_plan_header": "Plan:",
    "deploy.cd_plan_keygen": (
        "  1. Generate dedicated ed25519 deploy key (no passphrase)"
    ),
    "deploy.cd_plan_install": (
        "  2. Install public key in {user}@{host}:~/.ssh/authorized_keys"
    ),
    "deploy.cd_plan_secrets": (
        "  3. Push DEPLOY_SSH_KEY / DEPLOY_HOST / DEPLOY_USER to {repo} secrets"
    ),
    "deploy.cd_plan_workflow": "  4. Scaffold {path}",
    "deploy.cd_dry_run": "Dry run; no changes made.",
    "deploy.cd_generating_key": "Generating ed25519 deploy key...",
    "deploy.cd_keygen_failed": "ssh-keygen failed: {error}",
    "deploy.cd_installing_pubkey": ("Installing public key on {user}@{host}..."),
    "deploy.cd_install_failed": "Failed to install public key: {error}",
    "deploy.cd_pushing_secrets": "Pushing secrets to {repo}...",
    "deploy.cd_secret_failed": "Failed to set secret {name}: {error}",
    "deploy.cd_writing_workflow": "Writing {path}...",
    "deploy.cd_kept_key": "  Private key copy saved to {path}",
    "deploy.cd_complete": "GitHub Actions CD configured!",
    "deploy.cd_fingerprint": "  Deploy key fingerprint: {fingerprint}",
    "deploy.cd_next_commit": "  Next: commit {path} and push.",
    "deploy.cd_next_run": ("  Then trigger a deploy from the Actions tab on GitHub."),
    "deploy.cd_key_discarded": (
        "Note: the private key was sent to GitHub secrets and discarded "
        "locally. GitHub secrets are write-only — you can't retrieve it later."
    ),
    "deploy.cd_key_recover_hint": (
        "  To keep a local copy on future setup, pass --keep-key PATH. "
        "To rotate and save a copy now, run: aegis deploy-cd-setup --force "
        "--keep-key PATH"
    ),
    "deploy.deploying": "Deploying to {host}...",
    "deploy.creating_backup": "Creating backup {timestamp}...",
    "deploy.backup_failed": "Failed to create backup: {error}",
    "deploy.backup_db": "Backing up PostgreSQL database...",
    "deploy.backup_db_neon": "Database is managed by Neon (branches / point-in-time restore); skipping local backup",
    "deploy.backup_db_failed": (
        "Warning: Database backup failed, continuing without it"
    ),
    "deploy.backup_created": "Backup created: {timestamp}",
    "deploy.backup_pruned": "Pruned old backup: {name}",
    "deploy.no_existing": ("No existing deployment found, skipping backup"),
    "deploy.syncing": "Syncing files to server...",
    "deploy.mkdir_failed": ("Failed to create remote directory '{path}'"),
    "deploy.sync_failed": "Failed to sync files",
    "deploy.copying_env": "Copying {file} to server as .env...",
    "deploy.env_copy_failed": "Failed to copy .env file",
    "deploy.stopping": "Stopping existing services...",
    "deploy.building": "Building and starting services on server...",
    "deploy.start_failed": "Failed to start services",
    "deploy.auto_rollback": "Auto-rolling back to previous version...",
    "deploy.health_waiting": "Waiting for containers to stabilize...",
    "deploy.health_attempt": ("Health check attempt {n}/{total}..."),
    "deploy.health_passed": "Health check passed",
    "deploy.health_retry": ("Health check failed, retrying in {interval}s..."),
    "deploy.health_all_failed": "All health check attempts failed",
    "deploy.rolled_back": "Rolled back to backup {timestamp}",
    "deploy.rollback_failed": ("Rollback failed! Manual intervention required."),
    "deploy.health_failed_hint": (
        "Deploy completed but health check failed. Check logs with: aegis deploy-logs"
    ),
    "deploy.complete": "Deployment complete!",
    "deploy.rolling_starting": "Rolling deploy to {host}...",
    "deploy.rolling_building": "Building webserver image...",
    "deploy.rolling_pausing": "Pausing worker queue...",
    "deploy.rolling_pause_failed": (
        "Could not SET pause flag; workers may get SIGTERMed mid-job."
    ),
    "deploy.rolling_draining": ("Waiting up to {seconds}s for workers to drain..."),
    "deploy.rolling_drain_timeout": (
        "Workers did not drain in time. Pause flag cleared; aborting."
    ),
    "deploy.rolling_recreating": "Recreating: {services}",
    "deploy.rolling_webserver": (
        "Rolling webserver: starting a new replica and polling health "
        "(up to {seconds}s)..."
    ),
    "deploy.rolling_rollout_failed": (
        "Rolling webserver swap failed; the previous container is still serving."
    ),
    "deploy.rolling_complete": "Rolling deploy complete!",
    "deploy.app_running": ("   Application running at: http://{host}"),
    "deploy.overseer": ("   Overseer dashboard: http://{host}/dashboard/"),
    "deploy.view_logs": "   View logs: aegis deploy-logs",
    "deploy.check_status": "   Check status: aegis deploy-status",
    "deploy.backup_complete": "Backup complete!",
    "deploy.creating_backup_on": "Creating backup on {host}...",
    "deploy.no_backups": "No backups found.",
    "deploy.backups_header": ("Backups on {host} ({count} total):"),
    "deploy.col_timestamp": "Timestamp",
    "deploy.col_size": "Size",
    "deploy.col_database": "Database",
    "deploy.rollback_hint": (
        "Rollback with: aegis deploy-rollback --backup <timestamp>"
    ),
    "deploy.no_backups_available": "No backups available.",
    "deploy.rolling_back": ("Rolling back to backup {backup} on {host}..."),
    "deploy.rollback_not_found": "Backup not found: {timestamp}",
    "deploy.rollback_stopping": "Stopping services...",
    "deploy.rollback_restoring": ("Restoring files from backup {timestamp}..."),
    "deploy.rollback_restore_failed": ("Failed to restore files: {error}"),
    "deploy.rollback_db": "Restoring database...",
    "deploy.rollback_db_neon": "Database recovery is managed by Neon (branches / point-in-time restore); skipping local restore",
    "deploy.rollback_pg_wait": "Waiting for PostgreSQL to be ready...",
    "deploy.rollback_pg_timeout": (
        "PostgreSQL did not become ready, attempting restore anyway"
    ),
    "deploy.rollback_db_failed": "Warning: Database restore failed",
    "deploy.rollback_starting": "Starting services...",
    "deploy.rollback_start_failed": ("Failed to start services after rollback"),
    "deploy.rollback_complete": "Rollback complete!",
    "deploy.rollback_failed_final": "Rollback failed!",
    "deploy.status_header": "Service status on {host}:",
    "deploy.stop_stopping": "Stopping services...",
    "deploy.stop_success": "Services stopped",
    "deploy.stop_failed": "Failed to stop services",
    "deploy.restart_restarting": "Restarting services...",
    "deploy.restart_success": "Services restarted",
    "deploy.restart_failed": "Failed to restart services",
    # ── Shared CLI help text ───────────────────────────────────────────
    "common.help_project_path_full": (
        "Path to the Aegis Stack project (default: current directory)"
    ),
    "common.help_project_path": ("Path to the project (default: current directory)"),
    "common.help_yes": "Skip confirmation prompt",
    "common.help_yes_plural": "Skip confirmation prompts",
    "common.help_interactive_components": "Use interactive component selection",
    "common.help_interactive_services": "Use interactive service selection",
    "common.help_force": "Force through version mismatch warnings",
    # ── init CLI help ──────────────────────────────────────────────────
    "init.help_arg_name": "Name of the new Aegis Stack project to create",
    "init.help_opt_components": (
        "Comma-separated list of components (redis,worker,scheduler,database)"
    ),
    "blueprints.title": "AVAILABLE BLUEPRINTS",
    "blueprints.none_available": "No blueprints available.",
    "blueprints.includes": "Includes: {names}",
    "blueprints.usage_hint": "Start a project from one:",
    "init.help_opt_blueprint": (
        "Start from a named blueprint (a preset component/service selection)"
    ),
    "init.unknown_blueprint": "Unknown blueprint: {name}. Available: {available}",
    "init.help_opt_python": (
        "Python version for generated project (3.11, 3.12, 3.13, or 3.14)"
    ),
    "init.help_opt_force": "Overwrite existing directory if it exists",
    "init.help_opt_directory": (
        "Directory to create the project in (default: current directory)"
    ),
    "init.help_opt_template_version": (
        "Generate from specific template version (tag, commit, or branch)"
    ),
    "init.help_opt_no_llm_sync": (
        "Skip LLM catalog sync after project generation (AI service only)"
    ),
    "init.help_opt_dev": (
        "Dev mode: read templates from working tree (uncommitted changes)"
    ),
    "init.help_opt_services": (
        "Services: {services}. AI options: ai[framework,backend,providers] "
        "where framework={frameworks}, backend={backends}, "
        "providers={providers}"
    ),
    # ── add CLI help ───────────────────────────────────────────────────
    "add.help_arg_components": (
        "Comma-separated list of components to add (scheduler,worker,database)"
    ),
    "add.help_opt_scheduler_backend": (
        "Scheduler backend: 'memory' (default), 'sqlite', or 'postgres' "
        "(the latter two enable persistence; must match the database engine)"
    ),
    # ── update CLI help ────────────────────────────────────────────────
    "update.help_opt_to_version": "Update to specific version (default: latest)",
    "update.help_opt_dry_run": "Preview changes without applying",
    "update.help_opt_template_path": (
        "Use custom template path instead of installed version"
    ),
    # ── remove CLI help ────────────────────────────────────────────────
    "remove.help_arg_components": (
        "Comma-separated list of components to remove (scheduler,worker,database)"
    ),
    # ── add-service CLI help ───────────────────────────────────────────
    "add_service.help_arg_services": (
        "Comma-separated list of services to add (auth,ai)"
    ),
    # ── remove-service CLI help ────────────────────────────────────────
    "remove_service.help_arg_services": (
        "Comma-separated list of services to remove (auth,ai,comms)"
    ),
    # ── ingress CLI help ───────────────────────────────────────────────
    "ingress.help_opt_domain": ("Domain name for TLS certificate (e.g., example.com)"),
    "ingress.help_opt_email": "Email for Let's Encrypt certificate notifications",
    # ── deploy CLI help ────────────────────────────────────────────────
    "deploy.help_opt_host": "Server IP address or hostname",
    "deploy.help_opt_user": "SSH user for deployment",
    "deploy.help_opt_path": "Deployment path on server",
    "deploy.help_opt_public_key": (
        "Path to a public key to install in the deploy user's authorized_keys "
        "(idempotent). Use this so you don't have to ssh-copy-id by hand "
        "before deploying."
    ),
    "deploy.help_opt_build": "Build images before deploying",
    "deploy.help_opt_backup": "Create backup before deploying",
    "deploy.help_opt_health": "Run health check after deploying",
    "deploy.help_opt_rolling": (
        "Zero-HTTP-downtime code-only deploy. Rolls the webserver by "
        "health-polling a new replica and pauses the worker queue so "
        "in-flight jobs finish cleanly. Skips DB migrations."
    ),
    "deploy.help_opt_drain_timeout": (
        "Seconds to wait for workers to drain after pausing the queue "
        "during a rolling deploy (default: 90)."
    ),
    "deploy.help_opt_rollout_timeout": (
        "Runaway-guard ceiling in seconds for the new webserver to become "
        "healthy during a rolling deploy. The container's own HEALTHCHECK "
        "budget (start_period + retries x interval) normally decides the "
        "outcome; this is just a hard cap (default: 900)."
    ),
    "deploy.help_opt_rollback_backup": (
        "Backup timestamp to rollback to (default: latest)"
    ),
    "deploy.help_opt_logs_follow": "Follow log output",
    "deploy.help_opt_logs_service": "Show logs for specific service",
    "deploy.help_opt_shell_service": "Service to connect to",
    "deploy.help_opt_gh_repo": (
        "GitHub repo as owner/name (default: auto-detect from git remote origin)"
    ),
    "deploy.help_opt_gh_tags": (
        "Also trigger the deploy workflow on pushes to v* tags"
    ),
    "deploy.help_opt_gh_overwrite": (
        "Overwrite existing GitHub secrets and deploy.yml workflow"
    ),
    "deploy.help_opt_dry_run": "Print planned actions without making any changes",
    "deploy.help_opt_local_key_path": (
        "Path to copy the generated private key to before cleanup. "
        "Default: no local copy (the key only lives in GitHub secrets)."
    ),
    # ── plugins CLI (typer.Typer + commands) ───────────────────────────
    "plugins.help": "Inspect installed Aegis plugins and search the registry",
    "plugins.cannot_read_answers": (
        "Could not read {path}: {error}. Compat checks will be skipped."
    ),
    # `aegis plugins list`
    "plugins.help_list": (
        "List installed plugins and their compatibility with this project."
    ),
    "plugins.help_opt_list_project_path": (
        "Project to evaluate compat against (defaults to cwd if it's an Aegis project)."
    ),
    "plugins.help_opt_list_verbose": "Show description column.",
    "plugins.section_in_tree": "In-tree (first-party)",
    "plugins.section_external": "External plugins",
    "plugins.col_name": "Name",
    "plugins.col_version": "Version",
    "plugins.col_kind": "Kind",
    "plugins.col_description": "Description",
    "plugins.col_status": "Status",
    "plugins.no_external_installed": (
        "No external plugins installed. "
        "Install one with: pip install aegis-plugin-<name>"
    ),
    # `aegis plugins info`
    "plugins.help_info": "Show detailed information about a single plugin.",
    "plugins.help_arg_info_name": "Plugin name (e.g. 'auth', 'scraper')",
    "plugins.help_opt_info_project_path": "Project to evaluate compat against.",
    "plugins.not_installed_named": "No plugin named '{name}' is installed.",
    "plugins.available_list": "Available: {names}",
    "plugins.label_first_party": "(first-party)",
    "plugins.label_verified": "(verified)",
    "plugins.label_unverified": "(community, unverified)",
    "plugins.label_kind": "Kind:",
    "plugins.label_type": "Type:",
    "plugins.label_requires_components": "Requires comp:",
    "plugins.label_recommends_components": "Recommends:",
    "plugins.label_requires_services": "Requires svcs:",
    "plugins.label_requires_plugins": "Requires plug:",
    "plugins.label_conflicts": "Conflicts:",
    "plugins.label_python_deps": "Python deps:",
    "plugins.deps_more": "(+{count} more)",
    "plugins.section_options": "Options",
    "plugins.option_choices": "choices:",
    "plugins.option_default": "default:",
    "plugins.option_auto_requires": "(has auto_requires)",
    "plugins.info_files": (
        "Files: {files}   Migrations: {migrations} ({tables} tables)   CLI: {cli}"
    ),
    "plugins.cli_yes": "yes",
    "plugins.cli_no": "no",
    "plugins.section_compat": "Compat",
    # `aegis plugins update`
    "plugins.help_update": (
        "Re-render an installed plugin's templates at its currently "
        "pip-installed version."
    ),
    "plugins.help_arg_update_name": (
        "Plugin to update. Required unless --all is given."
    ),
    "plugins.help_opt_update_all": (
        "Update every plugin currently in this project's _plugins."
    ),
    "plugins.help_opt_update_force": (
        "Apply the update even when the new plugin version's aegis_version "
        "constraint excludes the running CLI."
    ),
    "plugins.update_need_target": "Pass a plugin name or use --all.",
    "plugins.update_either_not_both": ("Pass either a plugin name OR --all, not both."),
    "plugins.update_no_plugins_installed": (
        "No plugins are installed in this project."
    ),
    "plugins.update_not_in_project": (
        "Plugin '{name}' is not installed in this project."
    ),
    "plugins.update_use_list_hint": (
        "Use `aegis plugins list` to see what's available, and "
        "`aegis add <name>` to install."
    ),
    "plugins.update_not_pip_installed": (
        "Plugin '{name}' is in the project's _plugins list but not currently "
        "pip-installed; run `pip install aegis-plugin-{name}` first."
    ),
    "plugins.update_already_at": "{name} (already at {version})",
    "plugins.update_forcing": ("Forcing update despite version mismatch: {error}"),
    "plugins.update_progress": "Updating plugin: {name} ({old} → {new})",
    "plugins.update_confirm_apply": "Apply update to '{name}'?",
    "plugins.update_skipped_by_user": "{name} (skipped by user)",
    "plugins.update_legacy_strings": (
        "Skipping legacy string-shaped _plugins entries: {entries}. "
        "Re-add them with `aegis add <name>` to upgrade to the current "
        "dict format."
    ),
    "plugins.update_summary_updated": "Updated: {count}",
    "plugins.update_summary_skipped": "Skipped: {count}",
    "plugins.update_summary_failed": "Failed: {count}",
    # `aegis plugins create`
    "plugins.help_create": "Scaffold a new aegis-plugin-<name> Python package.",
    "plugins.help_arg_create_name": (
        "Plugin name (lowercase, no hyphens). Becomes the Python package "
        "aegis_plugin_<name> and the install name aegis-plugin-<name>."
    ),
    "plugins.help_opt_create_target": (
        "Parent directory the plugin scaffold lands inside."
    ),
    "plugins.help_opt_create_author": "Author string for pyproject.toml + README.",
    "plugins.help_opt_create_description": "One-line plugin description.",
    "plugins.create_target_missing": "Target directory does not exist: {target}",
    "plugins.create_already_exists": "Directory already exists: {output}",
    "plugins.create_pick_different": (
        "Pick a different name or remove the existing directory."
    ),
    "plugins.create_starting": "Creating plugin: {name}",
    "plugins.create_label_target": "Target:",
    "plugins.create_label_author": "Author:",
    "plugins.create_label_description": "Description:",
    "plugins.create_default_marker": "(default)",
    "plugins.create_confirm": "Create the scaffold?",
    "plugins.create_cancelled": "Cancelled.",
    "plugins.create_success": "Created {count} files under {output}",
    "plugins.create_next_steps_header": "Next steps:",
    "plugins.create_next_steps_confirm_comment": ("confirm the plugin is discovered"),
    "plugins.create_next_steps_edit_comment": (
        "Edit src/aegis_plugin_<name>/plugin.py to add wiring"
    ),
    # `aegis plugins search`
    "plugins.help_search": "Search the official plugin registry.",
    "plugins.help_arg_search_keyword": "Optional keyword to search for",
    "plugins.search_not_available": "Plugin registry is not yet available.",
    "plugins.search_install_hint": (
        "For now: pip install aegis-plugin-<name>, then aegis plugins list."
    ),
    "plugins.search_future_keyword": (
        "Once the registry is live, this command will search for '{keyword}'."
    ),
    # ── Guided setup (aegis init full-screen flow) ──────────
    "guided.welcome.title": "AEGIS STACK",
    "guided.welcome.tagline": "Production-ready Python apps from day one.",
    "guided.welcome.body": "This guided setup walks through each building block with a short explanation so you can decide what your project needs. Pick only what you want now; everything can be added later with 'aegis add'.",
    "guided.corestack.title": "INCLUDED IN EVERY PROJECT",
    "guided.corestack.body": "Every Aegis project starts with these two, wired together and ready to run.",
    "guided.sidebar.components": "COMPONENTS",
    "guided.sidebar.services": "SERVICES",
    "guided.prompt.worker_backend": "Pick a worker backend",
    "guided.prompt.scheduler_backend": "Scheduler persistence: keep job history across restarts?",
    "guided.prompt.database_engine": "Database engine for {context}",
    "guided.prompt.postgres_provider": "PostgreSQL host for {context}",
    "guided.prompt.auth_level": "Authentication level",
    "guided.prompt.ai_framework": "AI framework",
    "guided.prompt.ai_providers": "AI providers: pick any to wire in",
    "guided.prompt.ai_storage": "AI conversation storage",
    "guided.prompt.ai_rag": "Add RAG: chat grounded in your own docs and code?",
    "guided.prompt.ai_voice": "Add voice: text-to-speech and speech-to-text?",
    "guided.note.one_datastore": "One datastore per project: choosing an engine here sets the project database, shared by anything else that stores data.",
    "guided.note.one_database_host": "One database per project: this host serves everything that stores data.",
    "guided.multi.hint": "Check as many as you like, then pick Continue.",
    "guided.choice.add": "Add",
    "guided.choice.skip": "Skip",
    "guided.screen.add_question": "Add {name}?",
    "guided.screen.too_small": "Terminal too small. Resize to at least {w}x{h}.",
    "guided.review.title": "YOUR BUILD",
    "guided.review.files_pane": "COMPONENT FILES",
    "guided.review.deps_pane": "DEPENDENCIES",
    "guided.review.counts": "{files} component files · {deps} dependencies",
    "guided.building.title": "Building {name} …",
    "guided.building.preparing": "Preparing …",
    "guided.building.note": "This can take a minute or two; uv does the heavy lifting.",
    "guided.hint.building": "building …",
    "guided.done.ready": "{name} is ready",
    "guided.done.body": "Project generated and dependencies installed.",
    "guided.done.next_steps": "NEXT STEPS",
    "guided.done.project_structure": "PROJECT STRUCTURE",
    "guided.done.recreate": "RECREATE THIS STACK ANYTIME",
    "guided.done.copy_note": "Press c to copy; the full command also prints below after you finish.",
    "guided.done.copied": "Copied to clipboard ✓",
    # ── Guided setup: nav chrome + component/service blurbs ──
    "guided.choice.continue": "Continue",
    "guided.header.label": "guided setup",
    "guided.hint.move": "move",
    "guided.hint.select": "select",
    "guided.hint.toggle": "toggle",
    "guided.hint.back": "back",
    "guided.hint.begin": "begin",
    "guided.hint.build": "build",
    "guided.hint.next": "next",
    "guided.hint.finish": "finish",
    "guided.hint.quit": "quit",
    "guided.hint.services": "skip to services",
    "guided.hint.copy": "copy command",
    "guided.hint.deps": "deps",
    "guided.hint.files": "files",
    "guided.review.core": "Core:",
    "guided.review.infrastructure": "Infrastructure:",
    "guided.review.web_frontend": "Web frontend:",
    "guided.review.services": "Services:",
    "guided.review.auto": "auto",
    "guided.review.build": "Build {name}",
    "guided.review.more": "… +{n} more",
    "guided.screen.requires": "Requires:",
    "guided.screen.added_automatically": "(added automatically)",
    "guided.screen.pairs": "Pairs well with:",
    "guided.screen.docs": "Docs:",
    "component.backend.long": "A FastAPI application serving your API, async from the ground up: typed routes, automatic OpenAPI docs, health checks, and a test suite already covering all of it.",
    "component.frontend.long": "A Flet dashboard showing live system health and the status of every component you pick here, ready to grow into your own views. Python end to end, no JavaScript build chain.",
    "component.worker.long": "Background task processing with your choice of backend: arq (the default), Dramatiq, or TaskIQ. Offload slow work like emails, exports, and third-party API calls so requests stay fast. Runs on Redis, which is added automatically.",
    "component.scheduler.long": "Background task scheduling and cron jobs using APScheduler. Run periodic work like cleanups, reports, and health checks on a schedule. Optional database persistence keeps job history and survives restarts.",
    "component.database.long": "Persistent storage with the SQLModel ORM, Alembic migrations, and connection pooling. SQLite gives you a zero-config file database for development; PostgreSQL is the production path. Most services build on this.",
    "component.redis.long": "In-memory data store used as a cache and message broker. Powers background job queues and pub/sub messaging between your services, and gives request handlers a fast shared cache.",
    "component.ingress.long": "Reverse proxy and traffic routing with Traefik: automatic service discovery, admin endpoint protection, and optional TLS via Let's Encrypt. The front door for deployments.",
    "component.observability.long": "Distributed tracing, metrics, and log correlation with Pydantic Logfire. Auto-instruments your application and adapts to whichever components you enable, so you can see what production is actually doing.",
    "component.htmx.long": "Server-rendered pages with Jinja2, htmx, and Alpine.js, styled with Tailwind and DaisyUI, served at / by the existing webserver alongside the Flet dashboard at /dashboard. Ships a generic landing page ready to grow into your own pages.",
    "service.auth.long": "Complete user management with JWT authentication, session cookies, and refresh-token rotation. Three levels: basic email/password, RBAC roles and permissions, or multi-tenant organizations. Includes registration, login, and an admin dashboard tab.",
    "service.ai.long": "A complete AI platform: multi-provider chat, an LLM catalog with roughly 2000 models, cost tracking with usage analytics, optional RAG for codebase-aware conversations, and optional voice (TTS/STT). Pick Pydantic AI or LangChain as the framework.",
    "service.comms.long": "Email, SMS, and voice calls using industry providers: Resend for email, Twilio for SMS and voice. Both have free tiers, so you can start without a credit card.",
    "service.insights.long": "Automated tracking of your project's adoption across GitHub, PyPI, Plausible Analytics, and Reddit. Collects on a schedule, stores history, and visualizes growth in the dashboard.",
    "service.payment.long": "Payment processing with Stripe: checkout sessions, subscriptions, webhooks, and refunds. Stripe's test mode needs no credit card, so you can build the full flow before going live.",
    "service.blog.long": "First-party Markdown publishing with database-backed posts, tags, drafts, and an editor UI in the dashboard. Import and export posts as plain Markdown with frontmatter.",
    # ── Guided setup: choice descriptions + build steps ──
    "guided.choice.name.in_memory": "In-memory",
    "guided.choice.scheduler.memory": "No persistence. Jobs reset on restart — skip if unsure.",
    "guided.choice.scheduler.sqlite": "Persist job history in a file database.",
    "guided.choice.scheduler.postgres": "Persist job history, production-grade.",
    "guided.choice.worker.arq": "Simple, well-tested async worker with minimal configuration. Best for I/O-bound tasks. The default.",
    "guided.choice.worker.dramatiq": "Multi-process actor model. Best for CPU-bound tasks that benefit from multiple OS processes.",
    "guided.choice.worker.taskiq": "Async-native with per-queue brokers and Redis Streams transport with acknowledgements.",
    "guided.choice.db.sqlite": "Zero-config file database. Great for development.",
    "guided.choice.db.postgres": "Production-grade, pooled connections.",
    "guided.choice.db_provider.container": "Local postgres:16 container, dev and prod.",
    "guided.choice.db_provider.neon": (
        "Serverless Postgres: cloud in prod, local container in dev."
    ),
    "guided.choice.auth.basic": "Email and password with JWT sessions.",
    "guided.choice.auth.rbac": "Adds roles and permissions.",
    "guided.choice.auth.org": "Multi-tenant organizations.",
    "guided.choice.framework.pydantic_ai": "Typed and lightweight. The default.",
    "guided.choice.framework.langchain": "Large ecosystem, many integrations.",
    "guided.choice.storage.memory": "No history, nothing to set up.",
    "guided.choice.storage.sqlite": "Persistent chat history in a file database.",
    "guided.choice.storage.postgres": "Persistent and production-grade.",
    "guided.choice.provider.public.desc": "Free public endpoint",
    "guided.choice.provider.public.pricing": "Free, no API key",
    "guided.choice.provider.openai.desc": "GPT models",
    "guided.choice.provider.openai.pricing": "Paid",
    "guided.choice.provider.anthropic.desc": "Claude models",
    "guided.choice.provider.anthropic.pricing": "Paid",
    "guided.choice.provider.google.desc": "Gemini models",
    "guided.choice.provider.google.pricing": "Free tier (Flash only)",
    "guided.choice.provider.groq.desc": "Fast inference",
    "guided.choice.provider.groq.pricing": "Free tier",
    "guided.choice.provider.mistral.desc": "Open models",
    "guided.choice.provider.mistral.pricing": "Mostly paid",
    "guided.choice.provider.cohere.desc": "Enterprise focus",
    "guided.choice.provider.cohere.pricing": "Limited free",
    "guided.choice.provider.ollama.desc": "Local inference",
    "guided.choice.provider.ollama.pricing": "Free (local)",
    "build.step.render": "Rendering project files",
    "build.step.deps": "Installing dependencies",
    "build.step.env": "Environment configuration",
    "build.step.migrate": "Applying migrations",
    "build.step.llm": "Syncing LLM catalog",
    "build.step.format": "Formatting code",
}
