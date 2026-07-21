"""
Service registry and specifications for Aegis Stack.

This module defines all available services (auth, payment, AI, etc.), their dependencies,
and metadata used for project generation and validation.
"""

from dataclasses import dataclass
from enum import Enum

from ..constants import (
    AIFrameworks,
    AIProviders,
    AnswerKeys,
    AuthLevels,
    ComponentNames,
    StorageBackends,
)
from ..i18n import t
from .file_manifest import FileManifest
from .migration_generator import (
    AGENTS_MIGRATION,
    AI_MIGRATION,
    AUTH_MIGRATION,
    AUTH_RBAC_MIGRATION,
    AUTH_TOKENS_MIGRATION,
    BLOG_MIGRATION,
    FINANCE_AUTH_LINK_MIGRATION,
    FINANCE_MIGRATION,
    INSIGHTS_MIGRATION,
    KNOWLEDGE_MIGRATION,
    ORG_MIGRATION,
    PAYMENT_AUTH_LINK_MIGRATION,
    PAYMENT_MIGRATION,
    SENTIMENT_MIGRATION,
    VOICE_MIGRATION,
)
from .option_spec import OptionMode, OptionSpec
from .plugins.spec import (
    FrontendWidgetWiring,
    PluginKind,
    PluginSpec,
    PluginWiring,
    RouterWiring,
    SymbolWiring,
)


class ServiceType(Enum):
    """Service type classifications."""

    AUTH = "auth"  # Authentication and authorization
    PAYMENT = "payment"  # Payment processing
    AI = "ai"  # AI and ML integrations
    NOTIFICATION = "notification"  # Email, SMS, push notifications
    ANALYTICS = "analytics"  # Usage analytics and metrics
    STORAGE = "storage"  # File storage and CDN
    CONTENT = "content"  # Content publishing and editorial workflows
    FINANCE = "finance"  # Personal finance aggregation and ledger


# Translation key for each service type's display header. Used by the
# ``aegis services`` listing and the interactive service-selection loops so
# a new ServiceType needs exactly one label entry per locale.
SERVICE_TYPE_I18N_KEYS: dict[ServiceType, str] = {
    ServiceType.AUTH: "services.type_auth",
    ServiceType.PAYMENT: "services.type_payment",
    ServiceType.AI: "services.type_ai",
    ServiceType.NOTIFICATION: "services.type_notification",
    ServiceType.ANALYTICS: "services.type_analytics",
    ServiceType.STORAGE: "services.type_storage",
    ServiceType.CONTENT: "services.type_content",
    ServiceType.FINANCE: "services.type_finance",
}


@dataclass(kw_only=True)
class ServiceSpec(PluginSpec):
    """Service-flavoured PluginSpec — back-compat alias for pre-R2 callers.

    Subclasses ``PluginSpec`` and pins ``kind`` to ``SERVICE`` by default, so
    ``ServiceSpec(name=..., type=..., description=...)`` still works without
    naming the kind. R2 of the plugin system refactor; see
    ``aegis/core/plugin_spec.py`` for the unified type.

    ``kw_only=True`` is required: ``PluginSpec`` has a required ``kind`` field
    followed by defaulted fields, and overriding ``kind`` with a default in
    this subclass would otherwise violate the "required field after default"
    dataclass rule. Pre-R2 callers all used keyword construction (verified
    by AST scan), so no real call sites are affected.
    """

    kind: PluginKind = PluginKind.SERVICE


# Service registry - single source of truth for all available services
SERVICES: dict[str, ServiceSpec] = {
    "auth": ServiceSpec(
        name="auth",
        docs_path="services/auth",
        marker_path="app/services/auth",
        type=ServiceType.AUTH,
        description="User authentication and authorization with JWT tokens",
        long_description=(
            "Complete user management with JWT authentication, session "
            "cookies, and refresh-token rotation. Three levels: basic "
            "email/password, RBAC roles and permissions, or multi-tenant "
            "organizations. Includes registration, login, and an admin "
            "dashboard tab."
        ),
        required_components=[ComponentNames.BACKEND, ComponentNames.DATABASE],
        # Round 7 wiring: routers + dashboard card/modal. Mirrors what
        # ``app/components/backend/api/routing.py.jinja`` and the
        # ``cards/__init__.py.jinja`` / ``modals/__init__.py.jinja``
        # currently inject via Jinja conditionals on include_auth /
        # include_oauth / include_auth_org. Predicates here read those
        # same flags from the merged options dict (see PluginWiring docs).
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.auth.router",
                    symbol="router",
                    alias="auth_router",
                    prefix="/api/v1",
                ),
                RouterWiring(
                    module="app.components.backend.api.auth.oauth",
                    symbol="router",
                    alias="oauth_router",
                    prefix="/api/v1",
                    when=lambda opts: bool(opts.get(AnswerKeys.AUTH_OAUTH)),
                ),
                RouterWiring(
                    module="app.components.backend.api.orgs.router",
                    symbol="router",
                    alias="org_router",
                    prefix="/api/v1",
                    when=lambda opts: bool(opts.get(AnswerKeys.AUTH_ORG)),
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.auth_card",
                    symbol="AuthCard",
                    modal_id="auth",
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.auth_modal",
                    symbol="AuthDetailDialog",
                    modal_id="auth",
                ),
            ],
            # FastAPI dependency providers — service-facade deps that
            # take an AsyncSession and return a service instance. These
            # used to live inline in the shared deps.py.jinja behind
            # ``{% if include_auth %}`` blocks. Round 7.x moves them
            # into ``app/services/auth/deps.py.jinja`` (Option-1 refactor),
            # and the shared template just imports them via this list.
            #
            # Org-scoped providers gate on ``include_auth_org`` because
            # the org/membership/invite tables only exist at that auth
            # level.
            deps_providers=[
                # Rate-limit deps live in
                # ``app.components.backend.security.rate_limit`` (issue #686
                # — the original ``middleware/rate_limit.py`` placement was
                # misleading because it isn't ASGI middleware). Re-exported
                # here so route handlers can ``from
                # app.components.backend.api.deps import login_rate_limit``.
                SymbolWiring(
                    module="app.components.backend.security.rate_limit",
                    symbol="login_rate_limit",
                ),
                SymbolWiring(
                    module="app.components.backend.security.rate_limit",
                    symbol="password_reset_rate_limit",
                ),
                SymbolWiring(
                    module="app.components.backend.security.rate_limit",
                    symbol="register_rate_limit",
                ),
                SymbolWiring(
                    module="app.components.backend.security.rate_limit",
                    symbol="resend_verification_rate_limit",
                ),
                SymbolWiring(
                    module="app.services.auth.deps",
                    symbol="get_user_service",
                ),
                SymbolWiring(
                    module="app.services.auth.deps",
                    symbol="get_org_service",
                    when=lambda opts: bool(opts.get(AnswerKeys.AUTH_ORG)),
                ),
                SymbolWiring(
                    module="app.services.auth.deps",
                    symbol="get_membership_service",
                    when=lambda opts: bool(opts.get(AnswerKeys.AUTH_ORG)),
                ),
                SymbolWiring(
                    module="app.services.auth.deps",
                    symbol="get_invite_service",
                    when=lambda opts: bool(opts.get(AnswerKeys.AUTH_ORG)),
                ),
            ],
        ),
        # R4-A: migrations declared on the spec. Pre-R4 these lived in a
        # MIGRATION_SPECS dict literal in migration_generator.py; that dict
        # is now derived from this list (and from the migrations field on
        # the AI / payment / insights specs).
        migrations=[
            AUTH_MIGRATION,
            AUTH_RBAC_MIGRATION,
            ORG_MIGRATION,
            AUTH_TOKENS_MIGRATION,
        ],
        # Bracket-syntax options: auth[level, engine, oauth]
        # e.g. auth[rbac], auth[org,postgres], auth[basic,oauth]
        options=[
            OptionSpec(
                name="level",
                mode=OptionMode.SINGLE,
                choices=list(AuthLevels.ALL),
                default=AuthLevels.BASIC,
            ),
            OptionSpec(
                name="engine",
                mode=OptionMode.SINGLE,
                choices=[StorageBackends.SQLITE, StorageBackends.POSTGRES],
                default=None,
                # Auto-add engine-specific database; service_resolver
                # normalisation drops the plain `database` already in
                # required_components when a bracket variant is added.
                auto_requires=lambda v: [f"{ComponentNames.DATABASE}[{v}]"]
                if v
                else [],
            ),
            OptionSpec(
                name="oauth",
                mode=OptionMode.FLAG,
                choices=["oauth"],
                default=False,
            ),
        ],
        # Mirrors the ``{%- if include_auth %}`` + cross-service blocks in
        # pyproject.toml.jinja. Auth contributes ``alembic`` (auth has
        # migrations) and ``email-validator`` (User.email is EmailStr).
        # Order matches the legacy render for byte-parity.
        pyproject_deps=[
            "python-jose[cryptography]==3.3.0",
            "bcrypt>=4.0.0",
            # Order matches the legacy pyproject.toml.jinja template's
            # block order so the plugin-renderer / legacy parity test
            # (test_pyproject_deps_parity) keeps passing.
            "alembic==1.16.5",
            "python-multipart==0.0.9",
            "email-validator==2.2.0",
        ],
        template_files=[
            "app/components/backend/api/auth/",
            "app/models/user.py",
            "app/models/org.py",
            "app/services/auth/",
            "app/core/security.py",
            # Frontend auth scaffolding (login/register/session views and
            # the auth-shell controls). Missing from this list meant
            # ``aegis add-service auth`` never rendered these on an
            # existing project — see issue #686.
            "app/components/frontend/auth/",
            "app/components/frontend/controls/auth/",
        ],
        files=FileManifest(
            # Mirrors cleanup_components() lines 486-499 (auth NOT enabled)
            # PLUS lines 685-692 (auth dashboard cleanup, same condition).
            # alembic removal is cross-spec (line 707-720), stays inline.
            primary=[
                "app/components/backend/api/auth",
                "app/models/user.py",
                "app/services/auth",
                "app/core/security.py",
                "app/cli/auth.py",
                ".claude/skills/protect-an-endpoint",
                "tests/api/test_auth_endpoints.py",
                "tests/services/test_auth_integration.py",
                # Goal service is auth-coupled (Goal.user_id FK to user table);
                # cleanup_components removes it on the auth-off path. Note: it
                # is also removed on the insights-off path (kept consistent
                # there too), so duplicate removal is fine — apply_cleanup_path
                # is idempotent on missing files.
                "tests/services/test_goal_service.py",
                # Frontend dashboard files
                "app/components/frontend/dashboard/cards/auth_card.py",
                "app/components/frontend/dashboard/modals/auth_modal.py",
                "app/components/frontend/dashboard/modals/auth_users_tab.py",
                "app/components/frontend/dashboard/modals/auth_sessions_tab.py",
                # Frontend auth views + controls (mirrors the template_files
                # entries above so disabling auth removes them).
                "app/components/frontend/auth",
                "app/components/frontend/controls/auth",
                # Entirely-gated stubs (templates wrapped in
                # ``{% if include_auth %}``). Removing them at init means a
                # later ``aegis add-service auth`` writes fresh content
                # instead of seeing empty files and bailing — see #686.
                "app/models/refresh_token.py",
                "tests/components/test_frontend_auth_session.py",
                "tests/services/test_refresh_service.py",
                "tests/test_factories_demo.py",
            ],
            # Option-gated files live in extras, not primary: the add path
            # copies an extras group only when its answer key is truthy
            # (``get_component_files(answers=...)``), while removal and the
            # spec-off init cleanup always cover the full footprint. Keeping
            # these in primary shipped org stubs and htmx login pages into
            # basic/non-htmx projects (issue #814).
            extras={
                # Org sub-feature files. The narrower "auth ON but auth_org
                # OFF" cleanup stays inline in cleanup_components() (it gates
                # on two answers).
                "include_auth_org": [
                    "app/models/org.py",
                    "app/components/backend/api/orgs",
                    "app/components/frontend/dashboard/modals/auth_orgs_tab.py",
                    "tests/services/test_org_integration.py",
                    "tests/api/test_org_endpoints.py",
                ],
                # htmx web frontend auth surface. Owned here, not by the htmx
                # component: these exist only when auth does, and an
                # htmx-without-auth project must not carry them. The reverse
                # gate (no htmx) is covered by the htmx spec owning the whole
                # web_frontend tree, so dropping either one removes them.
                "include_htmx": [
                    "app/components/web_frontend/templates/pages/auth",
                    "app/components/web_frontend/templates/components/auth_macros.html",
                    "app/components/web_frontend/static/js/auth.js",
                ],
            },
        ),
    ),
    "ai": ServiceSpec(
        name="ai",
        docs_path="services/ai",
        marker_path="app/services/ai",
        type=ServiceType.AI,
        description="AI chatbot service with multi-framework support",
        long_description=(
            "A complete AI platform: multi-provider chat, an LLM catalog "
            "with roughly 2000 models, cost tracking with usage analytics, "
            "optional RAG for codebase-aware conversations, and optional "
            "voice (TTS/STT). Pick Pydantic AI or LangChain as the "
            "framework."
        ),
        required_components=[ComponentNames.BACKEND],
        # Round 7 wiring: 4 conditional routers + dashboard card/modal.
        # Predicates read both this plugin's options ("voice", "rag")
        # and broader project state ("ai_backend", "ollama_mode") from
        # the merged opts dict. Mirrors routing.py.jinja lines 21-29 +
        # 65-73.
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.ai.router",
                    symbol="router",
                    alias="ai_router",
                ),
                RouterWiring(
                    module="app.components.backend.api.voice.router",
                    symbol="router",
                    alias="voice_router",
                    prefix="/api/v1",
                    when=lambda opts: bool(opts.get("ai_voice")),
                ),
                RouterWiring(
                    module="app.components.backend.api.llm.router",
                    symbol="router",
                    alias="llm_router",
                    prefix="/api/v1",
                    # Persistence only: the catalog is provider-agnostic,
                    # and the CLI llm command + Cloud Catalog tab (which
                    # call this API) ship on every DB-backed stack.
                    when=lambda opts: (
                        opts.get("ai_backend") != StorageBackends.MEMORY
                    ),
                ),
                RouterWiring(
                    module="app.components.backend.api.rag.router",
                    symbol="router",
                    alias="rag_router",
                    prefix="/api/v1",
                    when=lambda opts: bool(opts.get("ai_rag")),
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.ai_card",
                    symbol="AICard",
                    modal_id="ai",
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.ai_modal",
                    symbol="AIDetailDialog",
                    modal_id="ai",
                ),
            ],
        ),
        # R4-A: migrations declared on the spec.
        migrations=[
            AI_MIGRATION,
            AGENTS_MIGRATION,
            KNOWLEDGE_MIGRATION,
            SENTIMENT_MIGRATION,
            VOICE_MIGRATION,
        ],
        # Bracket-syntax options: ai[framework, backend, providers..., flags...]
        # e.g. ai[langchain,sqlite,openai], ai[pydantic-ai,postgres,rag,voice]
        options=[
            OptionSpec(
                name="framework",
                mode=OptionMode.SINGLE,
                choices=list(AIFrameworks.ALL),
                default=AIFrameworks.PYDANTIC_AI,
            ),
            OptionSpec(
                name="backend",
                mode=OptionMode.SINGLE,
                choices=[
                    StorageBackends.MEMORY,
                    StorageBackends.SQLITE,
                    StorageBackends.POSTGRES,
                ],
                default=StorageBackends.MEMORY,
                # Persistence backends auto-add the matching database engine.
                auto_requires=lambda v: [f"{ComponentNames.DATABASE}[{v}]"]
                if v != StorageBackends.MEMORY
                else [],
            ),
            OptionSpec(
                name="providers",
                mode=OptionMode.MULTI,
                choices=sorted(AIProviders.ALL),
                default=list(AIProviders.DEFAULT),
            ),
            OptionSpec(
                name="rag",
                mode=OptionMode.FLAG,
                choices=["rag"],
                default=False,
            ),
            OptionSpec(
                name="voice",
                mode=OptionMode.FLAG,
                choices=["voice"],
                default=False,
            ),
        ],
        pyproject_deps=[
            "{AI_FRAMEWORK_DEPS}",  # Dynamic framework + provider deps
        ],
        template_files=[
            "app/services/ai/",
            "app/cli/ai.py",
            "app/components/backend/api/ai/",
        ],
        files=FileManifest(
            # Mirrors cleanup_components() lines 517-542 (AI NOT enabled),
            # plus the analytics / llm catalog / rag dashboard tabs: they
            # belong to the AI footprint, so add/remove and the AI-off init
            # path all cover them. The narrower sub-feature cleanups (AI
            # memory backend, ollama=none, rag off) stay inline.
            primary=[
                "app/components/backend/api/ai",
                # LLM catalog API. Backend-conditional like ``app/cli/llm.py``
                # below (both are stripped inline for the memory backend), so
                # it rides in ``primary``; without it the retrofit path never
                # copies the dir and the modal's catalog tab 404s (issue #814).
                "app/components/backend/api/llm",
                "app/services/ai",
                "app/cli/ai.py",
                "app/cli/agents.py",
                "app/cli/ai_rendering.py",
                "app/cli/marko_terminal_renderer.py",
                "app/cli/chat_completer.py",
                "app/cli/slash_commands.py",
                "app/cli/llm.py",
                "app/cli/status_line.py",
                # ``app/core/formatting.py`` is NOT removed on AI-off —
                # it also backs the always-shipping API load test CLI +
                # dashboard tab (``format_relative_time``).
                "tests/api/test_ai_endpoints.py",
                "tests/services/test_conversation_persistence.py",
                "tests/cli/test_ai_rendering.py",
                "tests/cli/test_conversation_memory.py",
                "tests/cli/test_chat_completer.py",
                "tests/cli/test_llm_cli.py",
                "tests/cli/test_agents_cli.py",
                "tests/cli/test_slash_commands.py",
                "tests/cli/test_status_line.py",
                "tests/services/ai",
                "app/components/frontend/dashboard/cards/ai_card.py",
                "app/components/frontend/dashboard/modals/ai_modal.py",
                "app/components/frontend/dashboard/modals/ai_analytics_tab.py",
                "app/components/frontend/dashboard/modals/agents_tab.py",
                "app/components/frontend/dashboard/modals/llm_catalog_tab.py",
                "tests/components/frontend/test_ai_analytics_utils.py",
                "app/models/conversation.py",
            ],
            # rag/voice files render empty unless their option is enabled, so
            # they live in `extras` (kept out of the always-on add base) and
            # are pulled into the full footprint for `aegis remove ai`. The AI
            # memory backend / ollama mode cleanups stay inline.
            extras={
                "ai_rag": [
                    "app/components/backend/api/rag",
                    "app/services/rag",
                    "app/cli/rag.py",
                    "tests/services/rag",
                    # RAG-gated, so it belongs here rather than ``primary`` —
                    # otherwise the retrofit copies it even with ``ai_rag``
                    # off, rendering a dead RAG tab (issue #814). The modal's
                    # ``_HAS_RAG`` import guard handles its absence.
                    "app/components/frontend/dashboard/modals/rag_tab.py",
                ],
                "ai_voice": [
                    "app/components/backend/api/voice",
                    "app/services/ai/voice",
                    "tests/services/ai/voice",
                    "tests/api/test_voice_endpoints.py",
                    "app/components/frontend/dashboard/modals/voice_settings_tab.py",
                ],
            },
        ),
    ),
    "comms": ServiceSpec(
        name="comms",
        docs_path="services/comms",
        marker_path="app/services/comms",
        type=ServiceType.NOTIFICATION,
        description="Communications service with email (Resend), SMS and voice (Twilio)",
        long_description=(
            "Email, SMS, and voice calls using industry providers: Resend "
            "for email, Twilio for SMS and voice. Both have free tiers, so "
            "you can start without a credit card."
        ),
        required_components=[ComponentNames.BACKEND],
        # Round 7 wiring: single router + dashboard card/modal.
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.comms.router",
                    symbol="router",
                    alias="comms_router",
                    prefix="/api/v1",
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.comms_card",
                    symbol="CommsCard",
                    modal_id="comms",
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.comms_modal",
                    symbol="CommsDetailDialog",
                    modal_id="comms",
                ),
            ],
        ),
        pyproject_deps=[
            "resend>=2.4.0",
            "twilio>=9.3.7",
            "email-validator==2.2.0",
        ],
        template_files=[
            "app/services/comms/",
            "app/cli/comms.py",
            "app/components/backend/api/comms/",
        ],
        files=FileManifest(
            primary=[
                "app/components/backend/api/comms",
                "app/services/comms",
                "app/cli/comms.py",
                "tests/api/test_comms_endpoints.py",
                "tests/services/comms",
                "docs/services/comms",
                # Frontend dashboard files
                "app/components/frontend/dashboard/cards/comms_card.py",
                "app/components/frontend/dashboard/modals/comms_modal.py",
            ],
        ),
    ),
    "insights": ServiceSpec(
        name="insights",
        docs_path="services/insights",
        marker_path="app/services/insights",
        type=ServiceType.ANALYTICS,
        description="Adoption metrics and analytics with automated data collection",
        long_description=(
            "Automated tracking of your project's adoption across GitHub, "
            "PyPI, Plausible Analytics, and Reddit. Collects on a "
            "schedule, stores history, and visualizes growth in the "
            "dashboard."
        ),
        required_components=[
            ComponentNames.BACKEND,
            ComponentNames.DATABASE,
            ComponentNames.SCHEDULER,
        ],
        recommended_components=[ComponentNames.WORKER],
        # Round 7 wiring: insights router lives in api/insights.py (not
        # api/insights/router.py); see routing.py.jinja:34.
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.insights",
                    symbol="router",
                    alias="insights_router",
                    prefix="/api/v1",
                    # The inner router declares ``tags=["insights"]`` itself;
                    # adding it here would emit a duplicate tag on every
                    # endpoint. Keep this in sync with insights.py.jinja.
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.insights_card",
                    symbol="InsightsCard",
                    modal_id="service_insights",
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.insights_modal",
                    symbol="InsightsDetailDialog",
                    modal_id="service_insights",
                ),
            ],
            # FastAPI dependency providers — moved from inline definitions
            # in shared deps.py.jinja into ``app/services/insights/deps.py``.
            deps_providers=[
                SymbolWiring(
                    module="app.services.insights.deps",
                    symbol="get_insight_service",
                ),
                SymbolWiring(
                    module="app.services.insights.deps",
                    symbol="get_collector_service",
                ),
                SymbolWiring(
                    module="app.services.insights.deps",
                    symbol="get_query_service",
                ),
            ],
        ),
        # R4-A: migrations declared on the spec. The insights spec is
        # context-aware — at generation time it rebuilds itself with the
        # per-user variant if ``insights_per_user`` is on.
        migrations=[INSIGHTS_MIGRATION],
        # Bracket-syntax options: insights[sources..., per_user]
        # e.g. insights[github,pypi,plausible,reddit,per_user]
        options=[
            OptionSpec(
                name="sources",
                mode=OptionMode.MULTI,
                choices=["github", "pypi", "plausible", "reddit"],
                default=["github", "pypi"],
            ),
            OptionSpec(
                name="per_user",
                mode=OptionMode.FLAG,
                choices=["per_user"],
                default=False,
                # NB: ``auto_requires`` here would only let us add
                # COMPONENTS (the resolver validates each returned
                # string as a component name). We need to require the
                # ``auth`` SERVICE — declaring that lives in
                # ``validate_service_dependencies`` instead, which has
                # access to the full selected-services list and can
                # error with "insights[per_user] requires the auth
                # service" when missing. See that function for the
                # check.
            ),
        ],
        pyproject_deps=[
            "httpx>=0.27.0",  # HTTP client for API collectors
        ],
        template_files=[
            "app/services/insights/",
            "app/cli/insights.py",
            "app/components/backend/api/insights/",
        ],
        files=FileManifest(
            # Mirrors cleanup_components() lines 654-683 (insights NOT enabled).
            primary=[
                "app/services/insights",
                "app/components/backend/api/insights.py",
                "app/cli/insights.py",
                "tests/services/test_insights_collectors.py",
                "tests/services/test_insight_service.py",
                "tests/services/test_query_service.py",
                "tests/services/test_collector_service.py",
                "tests/services/test_collector_github_traffic.py",
                "tests/services/test_collector_github_events.py",
                "tests/services/test_collector_github_stars.py",
                "tests/services/test_collector_pypi.py",
                "tests/services/test_collector_plausible.py",
                "tests/services/test_collector_reddit.py",
                # Goal service tests — also removed on the auth-off path;
                # double-removal is fine (apply_cleanup_path is idempotent).
                "tests/services/test_goal_service.py",
                "tests/api/test_insights_endpoints.py",
                "tests/test_bulk_response.py",
                "tests/test_cache_integration.py",
                "app/components/frontend/dashboard/cards/insights_card.py",
                "app/components/frontend/dashboard/modals/insights_modal.py",
            ],
        ),
    ),
    "payment": ServiceSpec(
        name="payment",
        docs_path="services/payment",
        marker_path="app/services/payment",
        type=ServiceType.PAYMENT,
        description="Payment processing with Stripe (checkout, subscriptions, webhooks)",
        long_description=(
            "Payment processing with Stripe: checkout sessions, "
            "subscriptions, webhooks, and refunds. Stripe's test mode "
            "needs no credit card, so you can build the full flow before "
            "going live."
        ),
        required_components=[
            ComponentNames.BACKEND,
            ComponentNames.DATABASE,
        ],
        recommended_components=[ComponentNames.WORKER],
        # Round 7 wiring: 2 routers (API + pages) + dashboard card/modal.
        # Mirrors routing.py.jinja:36-38 + 80-83.
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.payment.router",
                    symbol="router",
                    alias="payment_router",
                    prefix="/api/v1",
                ),
                RouterWiring(
                    module="app.components.backend.api.payment.pages",
                    symbol="router",
                    alias="payment_pages_router",
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.payment_card",
                    symbol="PaymentCard",
                    modal_id="service_payment",
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.payment_modal",
                    symbol="PaymentDetailDialog",
                    modal_id="service_payment",
                ),
            ],
            # FastAPI dependency providers — moved from inline definitions
            # in shared deps.py.jinja into ``app/services/payment/deps.py``.
            deps_providers=[
                SymbolWiring(
                    module="app.services.payment.deps",
                    symbol="get_payment_service",
                ),
            ],
        ),
        # R4-A: migrations declared on the spec.
        migrations=[PAYMENT_MIGRATION, PAYMENT_AUTH_LINK_MIGRATION],
        pyproject_deps=[
            "alembic==1.16.5",
            "stripe>=11.0.0",
        ],
        template_files=[
            "app/services/payment/",
            "app/cli/payment.py",
            "app/components/backend/api/payment/",
        ],
        files=FileManifest(
            primary=[
                "app/components/backend/api/payment",
                "app/services/payment",
                "app/cli/payment.py",
                "tests/services/test_payment_service.py",
                "tests/services/test_payment_models.py",
                "tests/services/test_payment_catalog.py",
                "tests/services/test_payment_webhook_forwarder.py",
                "tests/cli/test_payment_trigger.py",
                "tests/api/test_payment_endpoints.py",
                # Backend lifecycle hooks (auto-forward stripe-cli webhooks in dev)
                "app/components/backend/startup/payment_webhook_forwarder.py",
                "app/components/backend/shutdown/payment_webhook_forwarder.py",
                # Frontend dashboard files
                "app/components/frontend/dashboard/cards/payment_card.py",
                "app/components/frontend/dashboard/modals/payment_modal.py",
            ],
        ),
    ),
    "blog": ServiceSpec(
        name="blog",
        docs_path="services/blog",
        marker_path="app/services/blog",
        type=ServiceType.CONTENT,
        description="Markdown blog with draft/publish workflow and tags",
        long_description=(
            "First-party Markdown publishing with database-backed posts, "
            "tags, drafts, and an editor UI in the dashboard. Import and "
            "export posts as plain Markdown with frontmatter."
        ),
        required_components=[
            ComponentNames.BACKEND,
            ComponentNames.DATABASE,
        ],
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.blog.router",
                    symbol="router",
                    alias="blog_router",
                    prefix="/api/v1",
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.blog_card",
                    symbol="BlogCard",
                    modal_id="service_blog",
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.blog_modal",
                    symbol="BlogDetailDialog",
                    modal_id="service_blog",
                ),
            ],
            deps_providers=[
                SymbolWiring(
                    module="app.services.blog.deps",
                    symbol="get_blog_service",
                ),
            ],
        ),
        migrations=[BLOG_MIGRATION],
        pyproject_deps=[
            "alembic==1.16.5",
            # /import endpoint uses UploadFile, which FastAPI lowers to a
            # multipart form parameter and requires python-multipart.
            "python-multipart==0.0.9",
            # YAML-frontmatter parser used by the export/import pipeline
            # (see app/services/blog/serialization.py).
            "python-frontmatter>=1.1.0",
        ],
        template_files=[
            "app/services/blog/",
            "app/components/backend/api/blog/",
        ],
        files=FileManifest(
            primary=[
                "app/components/backend/api/blog",
                "app/services/blog",
                "app/cli/blog.py",
                "tests/services/test_blog_service.py",
                "tests/services/test_blog_serialization.py",
                "tests/api/test_blog_endpoints.py",
                "app/components/frontend/dashboard/cards/blog_card.py",
                "app/components/frontend/dashboard/modals/blog_modal.py",
            ],
        ),
    ),
    "finance": ServiceSpec(
        name="finance",
        # docs_path is set once the docs/services/finance page ships.
        docs_path="",
        marker_path="app/services/finance",
        type=ServiceType.FINANCE,
        description="Experimental: personal finance aggregation (accounts, transactions, net worth, import)",
        long_description=(
            "EXPERIMENTAL: schema, APIs, and CLI surface may change between "
            "releases. "
            "Aggregates bank, credit-card, and brokerage accounts, imports "
            "Quicken/OFX/CSV files, tracks net worth over time, and surfaces "
            "recurring-spend insights. Connectivity ships behind provider "
            "flags (Plaid, SnapTrade); file import and manual accounts work "
            "with no third-party service. When the auth service is present, "
            "finance rows are owned by the app user (FK wired via the "
            "finance_auth_link migration); standalone finance is single-user."
        ),
        required_components=[
            ComponentNames.BACKEND,
            ComponentNames.DATABASE,
            ComponentNames.SCHEDULER,
        ],
        recommended_components=[ComponentNames.WORKER],
        # Auth is integrated-when-present (owner FK via finance_auth_link),
        # not required — mirrors payment_customer.user_id. Keeping it optional
        # lets the guided/interactive flows select finance without forcing a
        # service-to-service dependency they don't resolve.
        # FIN-11 adds the backend router + DI provider; FIN-18 adds the
        # dashboard card (net-worth headline) + modal (Accounts / Transactions).
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.components.backend.api.finance.router",
                    symbol="router",
                    alias="finance_router",
                    prefix="/api/v1",
                ),
            ],
            dashboard_cards=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.cards.finance_card",
                    symbol="FinanceCard",
                    modal_id="service_finance",
                ),
            ],
            dashboard_modals=[
                FrontendWidgetWiring(
                    module="app.components.frontend.dashboard.modals.finance_modal",
                    symbol="FinanceDetailDialog",
                    modal_id="service_finance",
                ),
            ],
            deps_providers=[
                SymbolWiring(
                    module="app.services.finance.deps",
                    symbol="get_finance_service",
                ),
            ],
        ),
        migrations=[FINANCE_MIGRATION, FINANCE_AUTH_LINK_MIGRATION],
        # Alembic is installed via the shared migration gate in
        # pyproject.toml.jinja; provider deps (plaid/...) land with their
        # tickets. ``ofxtools`` backs the OFX/QFX importer (gated on the
        # finance_import sub-flag in pyproject.toml.jinja). ``aegis add-service
        # finance`` bootstraps alembic itself, so no alembic pin is needed here.
        pyproject_deps=["ofxtools>=0.9.5", "python-multipart==0.0.9"],
        template_files=[
            "app/services/finance/",
            "app/components/backend/api/finance/",
            "app/components/backend/startup/finance_webhook_tunnel.py",
            "app/components/frontend/dashboard/cards/finance_card.py",
            "app/components/frontend/dashboard/modals/finance_modal.py",
            "app/cli/finance.py",
        ],
        files=FileManifest(
            primary=[
                "app/services/finance",
                "app/components/backend/api/finance",
                "app/components/frontend/dashboard/cards/finance_card.py",
                "app/components/frontend/dashboard/modals/finance_modal.py",
                "app/cli/finance.py",
                "tests/services/test_finance_models.py",
                "tests/services/test_finance_service.py",
                "tests/services/test_finance_import.py",
                "tests/services/test_finance_investments.py",
                "tests/services/test_finance_insights.py",
                "tests/services/test_finance_plaid.py",
                "tests/services/test_finance_snaptrade.py",
                "tests/services/test_finance_transfers.py",
                "tests/services/test_finance_webhook_tunnel.py",
                "tests/services/finance",
                "tests/api/test_finance_endpoints.py",
                "tests/cli/test_finance_cli.py",
                "tests/components/frontend/test_finance_connect_menu.py",
                "app/components/backend/startup/finance_webhook_tunnel.py",
            ],
        ),
    ),
}


def get_service(name: str) -> ServiceSpec:
    """Get service specification by name."""
    if name not in SERVICES:
        raise ValueError(f"Unknown service: {name}")
    return SERVICES[name]


def get_services_by_type(service_type: ServiceType) -> dict[str, ServiceSpec]:
    """Get all services of a specific type."""
    return {name: spec for name, spec in SERVICES.items() if spec.type == service_type}


def list_available_services() -> list[str]:
    """Get list of all available service names."""
    return list(SERVICES.keys())


def get_service_dependencies(service_name: str) -> list[str]:
    """
    Get all required components for a service.

    Args:
        service_name: Name of the service

    Returns:
        List of component names required by this service
    """
    if service_name not in SERVICES:
        return []

    service = SERVICES[service_name]
    return service.required_components.copy()


def validate_service_dependencies(
    selected_services: list[str], available_components: list[str]
) -> list[str]:
    """
    Validate that all required components are available for selected services.

    Args:
        selected_services: List of service names to validate
        available_components: List of available component names

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    for service_name in selected_services:
        if service_name not in SERVICES:
            errors.append(t("validation.unknown_service", name=service_name))
            continue

        service = SERVICES[service_name]

        # Check required components
        for required_comp in service.required_components:
            if required_comp not in available_components:
                errors.append(
                    f"Service '{service_name}' requires component '{required_comp}'"
                )

        # Check service conflicts
        if service.conflicts:
            for conflict in service.conflicts:
                if conflict in selected_services:
                    errors.append(
                        f"Service '{service_name}' conflicts with service '{conflict}'"
                    )

    return errors
