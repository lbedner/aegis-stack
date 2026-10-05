"""
Tests for TemplateGenerator class.

Tests the template context generation, particularly the AI service
auto-detection logic that selects sqlite backend when database component
is available.
"""

from pathlib import Path

from aegis.constants import AnswerKeys, AuthLevels, PostgresProviders, StorageBackends
from aegis.core.template_generator import TemplateGenerator


class TestNeonProviderNormalization:
    """Neon is a Postgres *provider*, not a separate engine.

    ``database[neon]`` must normalize to engine=postgres + provider=neon so every
    existing postgres template path is reused unchanged; the provider only layers
    on connection handling (pooled/direct URLs, connect_args) and the prod compose
    shape (no DB container in production).
    """

    def test_neon_normalizes_to_postgres_engine(self) -> None:
        """database[neon] -> engine=postgres, provider=neon in the context."""
        gen = TemplateGenerator("test-neon", ["database[neon]"])
        context = gen.get_template_context()
        assert context["database_engine"] == StorageBackends.POSTGRES
        assert context[AnswerKeys.POSTGRES_PROVIDER] == PostgresProviders.NEON

    def test_neon_attributes_exposed_on_generator(self) -> None:
        """The generator normalizes the engine and records the provider."""
        gen = TemplateGenerator("test-neon", ["database[neon]"])
        assert gen.database_engine == StorageBackends.POSTGRES
        assert gen.postgres_provider == PostgresProviders.NEON

    def test_postgres_uses_container_provider(self) -> None:
        """Plain database[postgres] is the local-container provider."""
        gen = TemplateGenerator("test-pg", ["database[postgres]"])
        context = gen.get_template_context()
        assert context["database_engine"] == StorageBackends.POSTGRES
        assert context[AnswerKeys.POSTGRES_PROVIDER] == PostgresProviders.CONTAINER

    def test_sqlite_defaults_to_container_provider(self) -> None:
        """SQLite leaves the (irrelevant) provider at its container default."""
        gen = TemplateGenerator("test-sqlite", ["database"])
        context = gen.get_template_context()
        assert context["database_engine"] == StorageBackends.SQLITE
        assert context[AnswerKeys.POSTGRES_PROVIDER] == PostgresProviders.CONTAINER

    def test_neon_keeps_database_engine_postgres_for_dependent_services(self) -> None:
        """AI storage auto-detect keys off database_engine; neon must read as postgres."""
        gen = TemplateGenerator(
            "test-neon-ai", ["database[neon]"], selected_services=["ai"]
        )
        assert gen.database_engine == StorageBackends.POSTGRES


class TestTemplateGeneratorAIAutoDetection:
    """Test AI backend auto-detection based on available components.

    When AI service is selected without explicit backend (no bracket syntax),
    the system should auto-detect and use sqlite if database is available.
    """

    def test_ai_without_database_defaults_to_memory(self) -> None:
        """AI service without database should use memory backend."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],  # No database
            selected_services=["ai"],
        )
        assert gen.ai_backend == StorageBackends.MEMORY

    def test_ai_with_database_auto_detects_sqlite(self) -> None:
        """AI service with database should auto-detect sqlite backend.

        This is the critical test for the auto-detection feature:
        when user specifies --services ai --components database,
        the AI backend should automatically use sqlite.
        """
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["ai"],
        )
        assert gen.ai_backend == StorageBackends.SQLITE

    def test_ai_explicit_memory_overrides_auto_detection(self) -> None:
        """Explicit ai[memory] should use memory even with database.

        User explicitly specifying memory backend should override auto-detection.
        """
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["ai[memory]"],
        )
        assert gen.ai_backend == StorageBackends.MEMORY

    def test_ai_explicit_sqlite_works(self) -> None:
        """Explicit ai[sqlite] should use sqlite."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],  # No database component
            selected_services=["ai[sqlite]"],
        )
        assert gen.ai_backend == StorageBackends.SQLITE

    def test_ai_with_database_bracket_syntax(self) -> None:
        """AI with database[sqlite] component should auto-detect sqlite."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database[sqlite]"],
            selected_services=["ai"],
        )
        assert gen.ai_backend == StorageBackends.SQLITE

    def test_no_ai_service_defaults_to_memory(self) -> None:
        """Without AI service, ai_backend should be memory (default)."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=[],  # No AI service
        )
        assert gen.ai_backend == StorageBackends.MEMORY

    def test_context_includes_correct_ai_backend(self) -> None:
        """Template context should include the auto-detected ai_backend."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["ai"],
        )
        context = gen.get_template_context()
        assert context["ai_backend"] == StorageBackends.SQLITE
        assert context["ai_with_persistence"] == "yes"

    def test_context_memory_backend_no_persistence(self) -> None:
        """Memory backend should set ai_with_persistence to 'no'."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai"],
        )
        context = gen.get_template_context()
        assert context["ai_backend"] == StorageBackends.MEMORY
        assert context["ai_with_persistence"] == "no"


class TestTemplateGeneratorMultipleServices:
    """Test AI auto-detection with multiple services."""

    def test_ai_with_auth_and_database(self) -> None:
        """AI + auth + database should auto-detect sqlite for AI."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["ai", "auth"],
        )
        assert gen.ai_backend == StorageBackends.SQLITE

    def test_ai_with_comms_and_database(self) -> None:
        """AI + comms + database should auto-detect sqlite for AI."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["ai", "comms"],
        )
        assert gen.ai_backend == StorageBackends.SQLITE


class TestTemplateGeneratorCommsService:
    """Test comms service handling in template context.

    These tests verify that include_comms is correctly set in the
    template context when comms service is selected.
    """

    def test_comms_service_sets_include_comms(self) -> None:
        """Comms service should set include_comms to 'yes' in context."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["comms"],
        )
        context = gen.get_template_context()
        assert context["include_comms"] == "yes"

    def test_no_comms_service_sets_include_comms_no(self) -> None:
        """Without comms service, include_comms should be 'no'."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=[],
        )
        context = gen.get_template_context()
        assert context["include_comms"] == "no"

    def test_comms_with_auth_both_included(self) -> None:
        """Both comms and auth services should be included when selected."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["comms", "auth"],
        )
        context = gen.get_template_context()
        assert context["include_comms"] == "yes"
        assert context["include_auth"] == "yes"

    def test_all_services_included(self) -> None:
        """All services should be included when all selected."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["comms", "auth", "ai", "blog"],
        )
        context = gen.get_template_context()
        assert context["include_comms"] == "yes"
        assert context["include_auth"] == "yes"
        assert context["include_ai"] == "yes"
        assert context["include_blog"] == "yes"


class TestTemplateGeneratorBlogService:
    """Test blog service handling in template context."""

    def test_blog_service_sets_include_blog(self) -> None:
        """Blog service should set include_blog to 'yes' in context."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["blog"],
        )
        context = gen.get_template_context()
        assert context["include_blog"] == "yes"

    def test_no_blog_service_sets_include_blog_no(self) -> None:
        """Without blog service, include_blog should be 'no'."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=[],
        )
        context = gen.get_template_context()
        assert context["include_blog"] == "no"


class TestCopierAnswersTemplate:
    """Test that the .copier-answers.yml.jinja template includes all service flags.

    This is a regression test to ensure new services are added to the answers template.
    Without this, services may work on first init but break on subsequent add/remove operations.
    """

    def test_copier_answers_template_includes_all_services(self) -> None:
        """The .copier-answers.yml.jinja template must include all service flags.

        CRITICAL: If a service flag is missing from this template, the service
        will work on first init but break when add-service/remove-service
        operations regenerate shared files (because the flag won't be saved).
        """
        # Find the template file
        template_path = (
            Path(__file__).parent.parent.parent
            / "aegis"
            / "templates"
            / "copier-aegis-project"
            / "{{ project_slug }}"
            / ".copier-answers.yml.jinja"
        )

        assert template_path.exists(), f"Template not found: {template_path}"

        template_content = template_path.read_text()

        # All service include flags that should be in the template
        required_service_flags = [
            "include_auth",
            "auth_level",
            "include_auth_rbac",
            "include_auth_org",
            "include_ai",
            "include_comms",  # This was missing and caused the bug!
            "include_blog",
            "include_insights",
            "include_research",
        ]

        for flag in required_service_flags:
            assert flag in template_content, (
                f"Service flag '{flag}' is missing from .copier-answers.yml.jinja - this will cause add/remove operations to break for this service!"
            )


class TestHtmxFrontendQuestion:
    """Test the include_htmx component question in copier.yml.

    The Flet frontend is a core component and always present. The htmx web
    frontend is additive, so it is a bool include flag like the other
    components, not a variant axis. It must have no `when` clause and must
    appear in .copier-answers.yml.jinja so `aegis update` preserves the
    choice and backfills it for pre-existing projects.
    """

    REPO_ROOT = Path(__file__).parent.parent.parent

    def test_copier_yml_has_include_htmx_question(self) -> None:
        """copier.yml must define include_htmx as a bool, off by default."""
        import yaml

        with open(self.REPO_ROOT / "copier.yml") as f:
            config = yaml.safe_load(f)

        assert AnswerKeys.HTMX in config
        question = config[AnswerKeys.HTMX]
        assert question["type"] == "bool"
        assert question["default"] is False
        assert "when" not in question

    def test_copier_answers_template_includes_htmx_flag(self) -> None:
        """include_htmx must persist in .copier-answers.yml.jinja.

        Without this, the choice is lost on `aegis update` and sync-render
        reconciliation cannot backfill it for pre-existing projects.
        """
        template_path = (
            self.REPO_ROOT
            / "aegis"
            / "templates"
            / "copier-aegis-project"
            / "{{ project_slug }}"
            / ".copier-answers.yml.jinja"
        )

        template_content = template_path.read_text()
        expected = f"{AnswerKeys.HTMX}: {{{{ {AnswerKeys.HTMX} }}}}"
        assert expected in template_content


class TestTemplateGeneratorVoice:
    """Test AI voice configuration in template context.

    These tests verify that the ai_voice flag is correctly set in the
    template context when the voice feature is enabled via bracket syntax.
    """

    def test_ai_voice_disabled_by_default(self) -> None:
        """AI voice should be disabled by default."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai"],
        )
        assert gen.ai_voice is False

    def test_ai_voice_enabled_with_bracket_syntax(self) -> None:
        """AI voice should be enabled with ai[voice] syntax."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai[voice]"],
        )
        assert gen.ai_voice is True

    def test_ai_voice_with_other_options(self) -> None:
        """AI voice should work with other bracket options."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["ai[sqlite, voice]"],
        )
        assert gen.ai_voice is True
        assert gen.ai_backend == StorageBackends.SQLITE

    def test_context_includes_ai_voice_no(self) -> None:
        """Template context should include ai_voice as 'no' when disabled."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai"],
        )
        context = gen.get_template_context()
        assert context["ai_voice"] == "no"

    def test_context_includes_ai_voice_yes(self) -> None:
        """Template context should include ai_voice as 'yes' when enabled."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai[voice]"],
        )
        context = gen.get_template_context()
        assert context["ai_voice"] == "yes"

    def test_no_ai_service_voice_disabled(self) -> None:
        """Without AI service, ai_voice should be disabled."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=[],
        )
        assert gen.ai_voice is False
        context = gen.get_template_context()
        assert context["ai_voice"] == "no"


class TestTemplateGeneratorRagAndVoice:
    """Test RAG and voice features together in template context."""

    def test_rag_disabled_by_default(self) -> None:
        """RAG should be disabled by default."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai"],
        )
        assert gen.ai_rag is False

    def test_rag_enabled_with_bracket_syntax(self) -> None:
        """RAG should be enabled with ai[rag] syntax."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai[rag]"],
        )
        assert gen.ai_rag is True
        assert gen.ai_voice is False

    def test_both_rag_and_voice_enabled(self) -> None:
        """Both RAG and voice should be enabled together."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=["database"],
            selected_services=["ai[sqlite, rag, voice]"],
        )
        assert gen.ai_rag is True
        assert gen.ai_voice is True
        assert gen.ai_backend == StorageBackends.SQLITE

    def test_context_with_both_features(self) -> None:
        """Template context should correctly reflect both features."""
        gen = TemplateGenerator(
            project_name="test-project",
            selected_components=[],
            selected_services=["ai[rag, voice]"],
        )
        context = gen.get_template_context()
        assert context["ai_rag"] == "yes"
        assert context["ai_voice"] == "yes"


class TestTemplateGeneratorAuthLevel:
    """Test auth service level configuration in template context.

    These tests verify that the auth_level and include_auth_rbac flags
    are correctly set in the template context when auth service is selected
    with different level specifications.
    """

    def setup_method(self) -> None:
        """Clear auth level selection before each test."""
        from aegis.cli.interactive import clear_auth_level_selection

        clear_auth_level_selection()

    def test_auth_basic_default(self) -> None:
        """Auth service should default to basic level."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth"],
        )
        assert gen.auth_level == AuthLevels.BASIC

    def test_auth_rbac_bracket_syntax(self) -> None:
        """Auth service with auth[rbac] syntax should set rbac level."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[rbac]"],
        )
        assert gen.auth_level == AuthLevels.RBAC

    def test_auth_basic_bracket_syntax(self) -> None:
        """Auth service with auth[basic] syntax should set basic level."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[basic]"],
        )
        assert gen.auth_level == AuthLevels.BASIC

    def test_no_auth_defaults_to_basic(self) -> None:
        """Without auth service, auth_level should default to basic."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=[],
        )
        assert gen.auth_level == AuthLevels.BASIC

    def test_context_auth_level_basic(self) -> None:
        """Template context should include auth_level as 'basic' when basic."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth"],
        )
        context = gen.get_template_context()
        assert context["auth_level"] == AuthLevels.BASIC

    def test_context_auth_basic_bracket_overrides_interactive_rbac(self) -> None:
        """Explicit auth[basic] should override prior interactive RBAC selection."""
        from aegis.cli.interactive import set_auth_level_selection

        set_auth_level_selection(service_name="auth", level="rbac")
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[basic]"],
        )
        context = gen.get_template_context()
        assert context["auth_level"] == "basic"
        assert context["include_auth_rbac"] == "no"

    def test_context_auth_level_rbac(self) -> None:
        """Template context should include auth_level as 'rbac' when rbac."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[rbac]"],
        )
        context = gen.get_template_context()
        assert context["auth_level"] == AuthLevels.RBAC

    def test_context_include_auth_rbac_no(self) -> None:
        """Template context should include_auth_rbac as 'no' when basic."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth"],
        )
        context = gen.get_template_context()
        assert context["include_auth_rbac"] == "no"

    def test_context_include_auth_rbac_yes(self) -> None:
        """Template context should include_auth_rbac as 'yes' when rbac."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[rbac]"],
        )
        context = gen.get_template_context()
        assert context["include_auth_rbac"] == "yes"

    def test_auth_with_other_services(self) -> None:
        """Auth with other services should preserve auth level."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=["database"],
            selected_services=["auth[rbac]", "ai"],
        )
        assert gen.auth_level == AuthLevels.RBAC
        context = gen.get_template_context()
        assert context["include_auth_rbac"] == "yes"
        assert context["include_ai"] == "yes"

    def test_auth_empty_brackets_defaults_to_basic(self) -> None:
        """Auth service with auth[] (empty brackets) should default to basic."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[]"],
        )
        assert gen.auth_level == AuthLevels.BASIC
        context = gen.get_template_context()
        assert context["include_auth_rbac"] == "no"

    def test_auth_org_bracket_syntax(self) -> None:
        """Auth service with auth[org] syntax should set org level."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[org]"],
        )
        assert gen.auth_level == AuthLevels.ORG

    def test_context_auth_org_implies_rbac(self) -> None:
        """Template context with org level should have both org and rbac flags."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[org]"],
        )
        context = gen.get_template_context()
        assert context["auth_level"] == AuthLevels.ORG
        assert context["include_auth_org"] == "yes"
        assert context["include_auth_rbac"] == "yes"

    # ---- OAuth modifier (auth[oauth]) -------------------------------

    def test_bare_auth_omits_oauth(self) -> None:
        """Plain ``auth`` (no bracket) -> include_oauth='no'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth"],
        )
        assert gen.include_oauth is False
        context = gen.get_template_context()
        assert context["include_oauth"] == "no"

    def test_auth_basic_bracket_omits_oauth(self) -> None:
        """``auth[basic]`` without modifier -> include_oauth='no'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[basic]"],
        )
        assert gen.include_oauth is False
        context = gen.get_template_context()
        assert context["include_oauth"] == "no"

    def test_auth_oauth_bracket_syntax(self) -> None:
        """``auth[oauth]`` -> level=basic, include_oauth='yes'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[oauth]"],
        )
        assert gen.auth_level == AuthLevels.BASIC
        assert gen.include_oauth is True
        context = gen.get_template_context()
        assert context["auth_level"] == AuthLevels.BASIC
        assert context["include_oauth"] == "yes"
        # OAuth is independent of RBAC; basic-level oauth must NOT
        # implicitly turn rbac on.
        assert context["include_auth_rbac"] == "no"

    def test_auth_rbac_oauth_bracket_syntax(self) -> None:
        """``auth[rbac,oauth]`` -> level=rbac, include_oauth='yes'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[rbac,oauth]"],
        )
        assert gen.auth_level == AuthLevels.RBAC
        assert gen.include_oauth is True
        context = gen.get_template_context()
        assert context["auth_level"] == AuthLevels.RBAC
        assert context["include_auth_rbac"] == "yes"
        assert context["include_oauth"] == "yes"

    def test_auth_org_oauth_bracket_syntax(self) -> None:
        """``auth[org,oauth]`` -> level=org, include_oauth='yes'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[org,oauth]"],
        )
        context = gen.get_template_context()
        assert context["auth_level"] == AuthLevels.ORG
        assert context["include_auth_org"] == "yes"
        assert context["include_auth_rbac"] == "yes"
        assert context["include_oauth"] == "yes"

    def test_auth_oauth_order_independent(self) -> None:
        """``auth[oauth,rbac]`` parses identically to ``auth[rbac,oauth]``."""
        gen_a = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[oauth,rbac]"],
        )
        gen_b = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["auth[rbac,oauth]"],
        )
        ctx_a = gen_a.get_template_context()
        ctx_b = gen_b.get_template_context()
        assert ctx_a["auth_level"] == ctx_b["auth_level"] == AuthLevels.RBAC
        assert ctx_a["include_oauth"] == ctx_b["include_oauth"] == "yes"

    def test_no_auth_service_omits_oauth(self) -> None:
        """No auth service at all -> include_oauth='no'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=[],
        )
        assert gen.include_oauth is False
        context = gen.get_template_context()
        assert context["include_oauth"] == "no"


class TestTemplateGeneratorInsightsService:
    """Test insights service handling in template context."""

    def test_insights_sets_include_flag(self) -> None:
        """Insights service sets include_insights to 'yes'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["insights"],
        )
        context = gen.get_template_context()
        assert context["include_insights"] == "yes"

    def test_no_insights_sets_flag_no(self) -> None:
        """Without insights, include_insights is 'no'."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=[],
        )
        context = gen.get_template_context()
        assert context["include_insights"] == "no"

    def test_insights_default_sources(self) -> None:
        """Plain 'insights' defaults to github + pypi sources."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["insights"],
        )
        context = gen.get_template_context()
        assert context["insights_github"] == "yes"
        assert context["insights_pypi"] == "yes"
        assert context["insights_plausible"] == "no"
        assert context["insights_reddit"] == "no"

    def test_insights_bracket_all_sources(self) -> None:
        """Bracket syntax enables specified sources."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["insights[github,pypi,plausible,reddit]"],
        )
        context = gen.get_template_context()
        assert context["include_insights"] == "yes"
        assert context["insights_github"] == "yes"
        assert context["insights_pypi"] == "yes"
        assert context["insights_plausible"] == "yes"
        assert context["insights_reddit"] == "yes"

    def test_insights_bracket_single_source(self) -> None:
        """Bracket with single source only enables that one."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=[],
            selected_services=["insights[plausible]"],
        )
        context = gen.get_template_context()
        assert context["include_insights"] == "yes"
        assert context["insights_github"] == "no"
        assert context["insights_pypi"] == "no"
        assert context["insights_plausible"] == "yes"
        assert context["insights_reddit"] == "no"

    def test_insights_with_other_services(self) -> None:
        """Insights alongside other services — all flags correct."""
        gen = TemplateGenerator(
            project_name="test",
            selected_components=["database"],
            selected_services=["insights", "auth"],
        )
        context = gen.get_template_context()
        assert context["include_insights"] == "yes"
        assert context["include_auth"] == "yes"
        assert context["insights_github"] == "yes"
        assert context["insights_pypi"] == "yes"
