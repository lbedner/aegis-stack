"""
Tests for AI service configuration system.

This module tests the interactive provider selection, configuration loading,
and CLI commands for AI service management.
"""

from typing import Any
from unittest.mock import patch

from aegis.cli.interactive import (
    clear_ai_backend_selection,
    clear_ai_provider_selection,
    clear_database_engine_selection,
    clear_ollama_mode_selection,
    get_ai_backend_selection,
    get_ai_provider_selection,
    interactive_project_selection,
    set_database_engine_selection,
)


class TestAIProviderSelection:
    """Test cases for AI provider selection in interactive mode."""

    def setup_method(self) -> None:
        """Clear provider selection before each test."""
        clear_ai_provider_selection()

    @patch("typer.confirm")
    def test_ai_service_with_default_providers(self, mock_confirm: Any) -> None:
        """Test AI service selection with default providers."""
        # Mock user responses: no components, yes AI service, no to all specific providers (triggers defaults)
        mock_confirm.side_effect = [
            False,  # redis
            False,  # worker
            False,  # scheduler
            False,  # database
            False,  # ingress
            False,  # observability
            False,  # htmx
            False,  # auth service
            False,  # payment
            True,  # AI service
            False,  # Use PydanticAI? (framework, default True)
            False,  # Enable usage tracking with SQLite? No (memory backend)
            False,  # public (LLM7.io)
            False,  # openai
            False,  # anthropic
            False,  # google
            False,  # groq
            False,  # mistral
            False,  # cohere
            False,  # ollama
            True,  # Enable RAG? Yes (default)
            True,  # Enable voice?
            False,  # comms
            False,  # insights
            False,  # blog service
            False,  # finance service
            False,  # documents service
        ]

        components, scheduler_backend, services, _ = interactive_project_selection()

        # Verify AI service was selected (now uses bracket syntax like ai[backend,framework,...])
        assert any(s.startswith("ai") for s in services)
        assert scheduler_backend == "memory"

        # Verify default providers were selected
        providers = get_ai_provider_selection("ai")
        assert providers == ["public"]  # Interactive default when all declined

    @patch("typer.confirm")
    def test_ai_service_with_custom_providers(self, mock_confirm: Any) -> None:
        """Test AI service selection with custom provider selection."""
        # Mock user responses: no components, yes AI service, select openai and anthropic
        mock_confirm.side_effect = [
            False,  # redis
            False,  # worker
            False,  # scheduler
            False,  # database
            False,  # ingress
            False,  # observability
            False,  # htmx
            False,  # auth service
            False,  # payment
            True,  # AI service
            True,  # Use LangChain? Yes
            False,  # Enable usage tracking with SQLite? No (memory backend)
            False,  # public (LLM7.io)
            True,  # openai
            True,  # anthropic
            False,  # google
            False,  # groq
            False,  # mistral
            False,  # cohere
            False,  # ollama
            True,  # Enable RAG? Yes (default)
            True,  # Enable voice?
            False,  # comms
            False,  # insights
            False,  # blog service
            False,  # finance service
            False,  # documents service
        ]

        components, scheduler_backend, services, _ = interactive_project_selection()

        # Verify AI service was selected
        assert any(s.startswith("ai") for s in services)

        # Verify custom providers were selected
        providers = get_ai_provider_selection("ai")
        assert "openai" in providers
        assert "anthropic" in providers
        assert len(providers) == 2

    @patch("typer.confirm")
    def test_ai_service_with_recommended_providers(self, mock_confirm: Any) -> None:
        """Test AI service selection with recommended providers selected by default."""
        # Mock user responses: no components, yes AI service, accept recommended defaults
        mock_confirm.side_effect = [
            False,  # redis
            False,  # worker
            False,  # scheduler
            False,  # database
            False,  # ingress
            False,  # observability
            False,  # htmx
            False,  # auth service
            False,  # payment
            True,  # AI service
            False,  # Use LangChain? No (use PydanticAI)
            False,  # Enable usage tracking with SQLite? No (memory backend)
            False,  # public (LLM7.io)
            False,  # openai
            False,  # anthropic
            True,  # google (recommended)
            True,  # groq (recommended)
            False,  # mistral
            False,  # cohere
            False,  # ollama
            True,  # Enable RAG? Yes (default)
            True,  # Enable voice?
            False,  # comms
            False,  # insights
            False,  # blog service
            False,  # finance service
            False,  # documents service
        ]

        components, scheduler_backend, services, _ = interactive_project_selection()

        # Verify AI service was selected
        assert any(s.startswith("ai") for s in services)

        # Verify recommended providers were selected
        providers = get_ai_provider_selection("ai")
        assert "google" in providers
        assert "groq" in providers
        assert len(providers) == 2

    @patch("typer.confirm")
    def test_no_ai_service_selection(self, mock_confirm: Any) -> None:
        """Test when AI service is not selected."""
        # Mock user responses: no components, no services
        mock_confirm.side_effect = [
            False,  # redis
            False,  # worker
            False,  # scheduler
            False,  # database
            False,  # ingress
            False,  # observability
            False,  # htmx
            False,  # auth service
            False,  # payment
            False,  # AI service
            False,  # comms
            False,  # insights
            False,  # blog service
            False,  # finance service
            False,  # documents service
        ]

        components, scheduler_backend, services, _ = interactive_project_selection()

        # Verify AI service was not selected
        assert "ai" not in services
        assert services == []

        # Verify no provider selection was stored
        providers = get_ai_provider_selection("ai")
        assert providers == ["openai"]  # Default when not selected


class TestAIBackendSelection:
    """Test cases for AI backend selection (memory vs sqlite) in interactive mode."""

    def setup_method(self) -> None:
        """Clear selections before each test."""
        clear_ai_provider_selection()
        clear_ai_backend_selection()
        clear_database_engine_selection()

    @patch("typer.confirm")
    def test_ai_backend_selection_sqlite_auto_adds_database(
        self, mock_confirm: Any
    ) -> None:
        """Test that selecting SQLite backend auto-adds database component."""
        # Pre-set database engine (avoids interactive questionary prompt)
        set_database_engine_selection("sqlite")

        try:
            # Mock user responses: no components, yes AI service, yes SQLite tracking with sync
            mock_confirm.side_effect = [
                False,  # worker
                False,  # scheduler
                False,  # database
                False,  # redis
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                True,  # AI service
                False,  # Use LangChain? No (use PydanticAI)
                True,  # Enable usage tracking? Yes
                True,  # Sync LLM catalog during project generation? Yes
                False,  # public (LLM7.io)
                False,  # openai
                False,  # anthropic
                True,  # google
                True,  # groq
                False,  # mistral
                False,  # cohere
                False,  # ollama
                True,  # Enable RAG? Yes (default)
                True,  # Enable voice?
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            # Verify AI service was selected
            assert any(s.startswith("ai") for s in services)

            # Verify database component was auto-added
            assert any("database" in comp for comp in components)

            # Verify backend selection is sqlite
            backend = get_ai_backend_selection("ai")
            assert backend == "sqlite"
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_ai_backend_selection_sqlite_with_existing_database(
        self, mock_confirm: Any
    ) -> None:
        """Test SQLite backend with database already selected doesn't duplicate.

        One datastore, used everywhere: with a database in the project, the
        usage-tracking confirm is never asked — AI persists to it.
        """
        # Pre-set database engine (avoids interactive questionary prompt)
        set_database_engine_selection("sqlite")

        try:
            # Mock user responses: yes database, yes AI service, sync prompt
            mock_confirm.side_effect = [
                False,  # worker
                False,  # scheduler
                True,  # database (yes)
                False,  # redis
                False,  # ingress
                False,  # observability
                False,  # htmx
                False,  # auth service
                False,  # payment
                True,  # AI service
                False,  # Use LangChain? No (use PydanticAI)
                # (no usage-tracking confirm: project database is reused)
                True,  # Sync LLM catalog during project generation? Yes
                False,  # public (LLM7.io)
                False,  # openai
                False,  # anthropic
                True,  # google
                True,  # groq
                False,  # mistral
                False,  # cohere
                False,  # ollama
                True,  # Enable RAG? Yes (default)
                True,  # Enable voice?
                False,  # comms
                False,  # insights
                False,  # blog service
                False,  # finance service
                False,  # documents service
            ]

            components, scheduler_backend, services, _ = interactive_project_selection()

            # Verify AI service was selected
            assert any(s.startswith("ai") for s in services)

            # Verify database appears only once (no duplicate)
            database_count = sum(1 for comp in components if "database" in comp)
            assert database_count == 1

            # Verify backend selection is sqlite
            backend = get_ai_backend_selection("ai")
            assert backend == "sqlite"
        finally:
            clear_database_engine_selection()

    @patch("typer.confirm")
    def test_ai_backend_selection_memory(self, mock_confirm: Any) -> None:
        """Test that declining SQLite keeps memory backend."""
        # Mock user responses: no components, yes AI service, no SQLite tracking
        mock_confirm.side_effect = [
            False,  # redis
            False,  # worker
            False,  # scheduler
            False,  # database
            False,  # ingress
            False,  # observability
            False,  # htmx
            False,  # auth service
            False,  # payment
            True,  # AI service
            False,  # Use LangChain? No (use PydanticAI)
            False,  # Enable usage tracking with SQLite? No (memory)
            False,  # public (LLM7.io)
            False,  # openai
            False,  # anthropic
            True,  # google
            True,  # groq
            False,  # mistral
            False,  # cohere
            False,  # ollama
            True,  # Enable RAG? Yes (default)
            True,  # Enable voice?
            False,  # comms
            False,  # insights
            False,  # blog service
            False,  # finance service
            False,  # documents service
        ]

        components, scheduler_backend, services, _ = interactive_project_selection()

        # Verify AI service was selected
        assert any(s.startswith("ai") for s in services)

        # Verify no database was auto-added
        assert not any("database" in comp for comp in components)

        # Verify backend selection is memory
        backend = get_ai_backend_selection("ai")
        assert backend == "memory"

    def test_ai_backend_selection_defaults(self) -> None:
        """Test that backend defaults to memory when not set."""
        clear_ai_backend_selection()

        # Should return memory as default
        backend = get_ai_backend_selection("ai")
        assert backend == "memory"

        # Should return memory for unknown service too
        backend = get_ai_backend_selection("unknown_service")
        assert backend == "memory"


class TestAIConfigurationIntegration:
    """Test AI configuration system integration."""

    def test_provider_selection_storage(self) -> None:
        """Test that provider selection is stored and retrieved correctly."""
        clear_ai_provider_selection()

        # Simulate provider selection
        from aegis.cli.interactive import _ai_provider_selection

        _ai_provider_selection["ai"] = ["openai", "google", "groq"]

        # Verify retrieval
        providers = get_ai_provider_selection("ai")
        assert providers == ["openai", "google", "groq"]

    def test_provider_selection_defaults(self) -> None:
        """Test default provider selection when none specified."""
        clear_ai_provider_selection()

        # Should return defaults when no selection made
        providers = get_ai_provider_selection("ai")
        assert providers == ["openai"]

        # Should return defaults for unknown service
        providers = get_ai_provider_selection("unknown_service")
        assert providers == ["openai"]

    def test_clear_provider_selection(self) -> None:
        """Test clearing provider selection."""
        # Set some providers
        from aegis.cli.interactive import _ai_provider_selection

        _ai_provider_selection["ai"] = ["openai"]

        # Verify they're set
        providers = get_ai_provider_selection("ai")
        assert providers == ["openai"]

        # Clear and verify defaults return
        clear_ai_provider_selection()
        providers = get_ai_provider_selection("ai")
        assert providers == ["openai"]


class TestTemplateGeneratorIntegration:
    """Test integration with template generator for dynamic dependencies."""

    def test_ai_providers_string_generation(self) -> None:
        """Test that template generator creates correct provider string."""
        from aegis.cli.interactive import _ai_provider_selection
        from aegis.core.template_generator import TemplateGenerator

        # Set up provider selection
        clear_ai_provider_selection()
        _ai_provider_selection["ai"] = ["openai", "anthropic", "google"]

        # Create template generator with AI service
        generator = TemplateGenerator(
            "test-project", selected_components=["backend"], selected_services=["ai"]
        )

        # Test provider string generation
        providers_string = generator._get_ai_providers_string()
        assert providers_string == "openai,anthropic,google"

    def test_ai_providers_string_no_service(self) -> None:
        """Test provider string generation when AI service not selected."""
        from aegis.core.template_generator import TemplateGenerator

        clear_ai_provider_selection()

        # Create template generator without AI service
        generator = TemplateGenerator(
            "test-project", selected_components=["backend"], selected_services=[]
        )

        # Should return defaults when service not selected
        providers_string = generator._get_ai_providers_string()
        assert providers_string == "openai"

    def test_template_context_includes_providers(self) -> None:
        """Test that template context includes AI provider selection."""
        from aegis.cli.interactive import _ai_provider_selection
        from aegis.core.template_generator import TemplateGenerator

        # Set up provider selection
        clear_ai_provider_selection()
        _ai_provider_selection["ai"] = ["groq", "google", "mistral"]

        # Create template generator with AI service
        generator = TemplateGenerator(
            "test-project", selected_components=["backend"], selected_services=["ai"]
        )

        # Get template context
        context = generator.get_template_context()

        # Verify AI provider context is included
        assert context["include_ai"] == "yes"
        assert context["ai_providers"] == "groq,google,mistral"


# Integration test scenarios
class TestAIConfigurationEndToEnd:
    """End-to-end tests for AI configuration system."""

    @patch("typer.confirm")
    def test_full_ai_configuration_flow(self, mock_confirm: Any) -> None:
        """Test complete flow from interactive selection to template generation."""
        clear_ai_provider_selection()

        # Mock interactive selection with AI service and specific providers
        mock_confirm.side_effect = [
            False,  # redis
            False,  # worker
            False,  # scheduler
            False,  # database
            False,  # ingress
            False,  # observability
            False,  # htmx
            False,  # No auth service
            False,  # payment
            True,  # Yes AI service
            True,  # Use LangChain? Yes
            False,  # Enable usage tracking with SQLite? No (memory backend)
            False,  # public (LLM7.io) no
            True,
            False,
            True,
            True,
            False,
            False,
            False,  # Provider selection (openai yes, anthropic no, google yes, groq yes, mistral no, cohere no, ollama no)
            True,  # Enable RAG? Yes (default)
            True,  # Enable voice?
            False,  # comms
            False,  # insights
            False,  # blog service
            False,  # finance service
            False,  # documents service
        ]

        # Run interactive selection
        components, scheduler_backend, services, _ = interactive_project_selection()

        # Verify service selection
        assert any(s.startswith("ai") for s in services)

        # Verify provider selection
        providers = get_ai_provider_selection("ai")
        assert "openai" in providers
        assert "google" in providers
        assert "groq" in providers
        assert len(providers) == 3

        # Test template generation
        from aegis.core.template_generator import TemplateGenerator

        generator = TemplateGenerator(
            "test-ai-project",
            selected_components=components,
            selected_services=services,
        )

        context = generator.get_template_context()

        # Verify template context
        assert context["include_ai"] == "yes"
        assert context["ai_providers"] == "openai,google,groq"
        assert context["project_name"] == "test-ai-project"

    def test_copier_yaml_structure(self) -> None:
        """Test that copier.yml has correct AI provider structure."""
        from pathlib import Path

        import yaml

        # Load copier.yml directly
        copier_path = Path(__file__).parent.parent.parent / "copier.yml"

        with open(copier_path) as f:
            config = yaml.safe_load(f)

        # Verify AI-related fields exist
        assert "include_ai" in config
        assert "ai_providers" in config
        assert "_ai_deps" in config

        # Verify AI voice configuration exists
        assert "ai_voice" in config
        assert config["ai_voice"]["type"] == "bool"
        assert "when" in config["ai_voice"]  # Should be conditional on include_ai

        # Verify AI dependencies template uses provider variable
        ai_deps = config["_ai_deps"]
        assert "ai_providers" in ai_deps
        assert "pydantic-ai-slim" in ai_deps


class TestOllamaModeSelection:
    """Test cases for Ollama mode selection in interactive and non-interactive modes."""

    def setup_method(self) -> None:
        """Clear all AI selections before each test."""

        clear_ai_provider_selection()
        clear_ai_backend_selection()
        clear_ollama_mode_selection()

    @patch("typer.confirm")
    def test_ai_service_with_ollama_host_mode(self, mock_confirm: Any) -> None:
        """Test Ollama mode selection when Ollama is chosen as provider."""
        from aegis.cli.interactive import (
            get_ollama_mode_selection,
        )
        from aegis.constants import OllamaMode

        clear_ollama_mode_selection()  # Reset state

        mock_confirm.side_effect = [
            False,  # redis
            False,  # worker
            False,  # scheduler
            False,  # database
            False,  # ingress
            False,  # observability
            False,  # htmx
            False,  # auth service
            False,  # payment
            True,  # AI service
            False,  # Use LangChain? No
            False,  # Enable usage tracking? No
            False,  # public (LLM7.io)
            False,  # openai
            False,  # anthropic
            False,  # google
            False,  # groq
            False,  # mistral
            False,  # cohere
            True,  # SELECT Ollama
            True,  # Ollama mode: connect to host (True = HOST)
            True,  # Enable RAG
            True,  # Enable voice?
            False,  # comms
            False,  # insights
            False,  # blog service
            False,  # finance service
            False,  # documents service
        ]

        interactive_project_selection()

        # Verify Ollama mode was set correctly
        ollama_mode = get_ollama_mode_selection("ai")
        assert ollama_mode == OllamaMode.HOST

    def test_non_interactive_ollama_auto_default(self) -> None:
        """Test that ollama_mode defaults to HOST when ollama in providers (non-interactive)."""
        from aegis.cli.interactive import (
            get_ollama_mode_selection,
            set_ai_service_config,
        )
        from aegis.constants import AIProviders, OllamaMode

        clear_ollama_mode_selection()

        # Simulate bracket syntax: ai[sqlite,ollama]
        set_ai_service_config(
            service_name="ai",
            framework="pydantic-ai",
            backend="sqlite",
            providers=["openai", AIProviders.OLLAMA],
        )

        # Verify auto-default to HOST
        assert get_ollama_mode_selection("ai") == OllamaMode.HOST

    def test_non_interactive_no_ollama_defaults_none(self) -> None:
        """Test that ollama_mode defaults to NONE when ollama NOT in providers."""
        from aegis.cli.interactive import (
            get_ollama_mode_selection,
            set_ai_service_config,
        )
        from aegis.constants import OllamaMode

        clear_ollama_mode_selection()

        # Simulate bracket syntax without ollama: ai[sqlite]
        set_ai_service_config(
            service_name="ai",
            framework="pydantic-ai",
            backend="sqlite",
            providers=["openai", "anthropic"],
        )

        # Verify mode is NONE
        assert get_ollama_mode_selection("ai") == OllamaMode.NONE
