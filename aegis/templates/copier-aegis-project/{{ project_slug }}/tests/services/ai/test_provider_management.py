"""Tests for AI provider management utilities."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.ai.models import AIProvider
from app.services.ai.provider_management import (
    PROVIDER_API_KEY_URLS,
    PROVIDER_DEPENDENCIES,
    PROVIDER_MODULE_CHECKS,
    check_provider_dependency_installed,
    get_env_var_name,
    get_existing_api_key,
    get_missing_dependency,
    get_provider_api_key_url,
    get_valid_provider_names,
    mask_api_key,
    read_env_file,
    update_env_file,
    validate_provider_name,
)


class TestProviderDependencies:
    """Tests for provider dependency mappings."""

    def test_all_providers_have_dependencies(self) -> None:
        """All AIProvider enum values should have dependency mappings."""
        for provider in AIProvider:
            assert provider.value in PROVIDER_DEPENDENCIES, (
                f"Provider {provider.value} missing from PROVIDER_DEPENDENCIES"
            )

    def test_all_providers_have_module_checks(self) -> None:
        """All AIProvider enum values should have module check mappings."""
        for provider in AIProvider:
            assert provider.value in PROVIDER_MODULE_CHECKS, (
                f"Provider {provider.value} missing from PROVIDER_MODULE_CHECKS"
            )

    def test_dependency_format(self) -> None:
        """All dependencies should be valid package specifiers."""
        for provider, dependency in PROVIDER_DEPENDENCIES.items():
            assert "pydantic-ai-slim" in dependency, (
                f"Dependency for {provider} should be pydantic-ai-slim package"
            )
            assert "[" in dependency and "]" in dependency, (
                f"Dependency for {provider} should specify an extra"
            )


class TestCheckProviderDependencyInstalled:
    """Tests for dependency checking function."""

    @patch("importlib.util.find_spec")
    def test_dependency_installed(self, mock_find_spec: MagicMock) -> None:
        """Returns True when module spec is found."""
        mock_find_spec.return_value = MagicMock()  # Non-None spec
        assert check_provider_dependency_installed("openai") is True
        mock_find_spec.assert_called_once_with("openai")

    @patch("importlib.util.find_spec")
    def test_dependency_not_installed(self, mock_find_spec: MagicMock) -> None:
        """Returns False when module spec is None."""
        mock_find_spec.return_value = None
        assert check_provider_dependency_installed("anthropic") is False

    @patch("importlib.util.find_spec")
    def test_dependency_import_error(self, mock_find_spec: MagicMock) -> None:
        """Returns False when import raises ModuleNotFoundError."""
        mock_find_spec.side_effect = ModuleNotFoundError("No module")
        assert check_provider_dependency_installed("google") is False

    def test_unknown_provider(self) -> None:
        """Returns False for unknown provider names."""
        assert check_provider_dependency_installed("unknown_provider") is False
        assert check_provider_dependency_installed("") is False


class TestGetMissingDependency:
    """Tests for getting missing dependency package name."""

    @patch("app.services.ai.provider_management.check_provider_dependency_installed")
    def test_returns_package_when_not_installed(self, mock_check: MagicMock) -> None:
        """Returns package name when dependency is not installed."""
        mock_check.return_value = False
        result = get_missing_dependency("google")
        assert result == "pydantic-ai-slim[google]"

    @patch("app.services.ai.provider_management.check_provider_dependency_installed")
    def test_returns_none_when_installed(self, mock_check: MagicMock) -> None:
        """Returns None when dependency is already installed."""
        mock_check.return_value = True
        result = get_missing_dependency("openai")
        assert result is None


class TestEnvFileOperations:
    """Tests for .env file reading and writing."""

    def test_read_env_file(self, tmp_path: Path) -> None:
        """Read .env file correctly parses key-value pairs."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            """# Comment line
API_KEY=secret123
DEBUG=true
EMPTY=

# Another comment
WITH_QUOTES="quoted value"
"""
        )

        result = read_env_file(env_file)

        assert result["API_KEY"] == "secret123"
        assert result["DEBUG"] == "true"
        assert result["EMPTY"] == ""
        assert result["WITH_QUOTES"] == "quoted value"
        assert "Comment" not in str(result.keys())

    def test_read_env_file_not_exists(self, tmp_path: Path) -> None:
        """Returns empty dict when .env file doesn't exist."""
        env_file = tmp_path / ".env"
        result = read_env_file(env_file)
        assert result == {}

    def test_update_env_file_add_new_key(self, tmp_path: Path) -> None:
        """Add new key to existing .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=value\n")

        update_env_file({"NEW_KEY": "new_value"}, env_file)

        content = env_file.read_text()
        assert "EXISTING=value" in content
        assert "NEW_KEY=new_value" in content

    def test_update_env_file_update_existing_key(self, tmp_path: Path) -> None:
        """Update existing key in .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("MY_KEY=old_value\n")

        update_env_file({"MY_KEY": "new_value"}, env_file)

        content = env_file.read_text()
        assert "MY_KEY=new_value" in content
        assert "old_value" not in content

    def test_update_env_file_preserves_comments(self, tmp_path: Path) -> None:
        """Comments and formatting are preserved when updating."""
        env_file = tmp_path / ".env"
        env_file.write_text("# Important comment\nKEY=value\n")

        update_env_file({"NEW": "test"}, env_file)

        content = env_file.read_text()
        assert "# Important comment" in content

    def test_update_env_file_create_new(self, tmp_path: Path) -> None:
        """Create new .env file if it doesn't exist."""
        env_file = tmp_path / ".env"

        update_env_file({"NEW_KEY": "value"}, env_file)

        assert env_file.exists()
        content = env_file.read_text()
        assert "NEW_KEY=value" in content


class TestGetExistingApiKey:
    """Tests for checking existing API keys."""

    def test_from_env_file(self, tmp_path: Path) -> None:
        """API key found in .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-test-key\n")

        result = get_existing_api_key("openai", env_file)
        assert result == "sk-test-key"

    def test_from_environment_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variable takes precedence over .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=file-key\n")

        monkeypatch.setenv("OPENAI_API_KEY", "env-key")

        result = get_existing_api_key("openai", env_file)
        assert result == "env-key"

    def test_no_key_found(self, tmp_path: Path) -> None:
        """Returns None when no API key found."""
        env_file = tmp_path / ".env"
        env_file.write_text("")

        result = get_existing_api_key("anthropic", env_file)
        assert result is None


class TestGetEnvVarName:
    """Tests for environment variable name generation."""

    def test_openai(self) -> None:
        assert get_env_var_name("openai") == "OPENAI_API_KEY"

    def test_anthropic(self) -> None:
        assert get_env_var_name("anthropic") == "ANTHROPIC_API_KEY"

    def test_google(self) -> None:
        assert get_env_var_name("google") == "GOOGLE_API_KEY"


class TestProviderApiKeyUrls:
    """Tests for API key URL lookups."""

    def test_all_paid_providers_have_urls(self) -> None:
        """All paid providers should have API key URLs."""
        # PUBLIC and OLLAMA don't need API keys
        no_api_key_providers = {
            AIProvider.PUBLIC,
            AIProvider.OLLAMA,
            AIProvider.POLLINATIONS,
        }
        for provider in AIProvider:
            if provider not in no_api_key_providers:
                url = get_provider_api_key_url(provider.value)
                assert url is not None, f"Provider {provider.value} missing API key URL"
                assert url.startswith("https://"), (
                    f"URL for {provider.value} should be HTTPS"
                )

    def test_local_providers_have_no_url(self) -> None:
        """LOCAL providers (PUBLIC, OLLAMA) don't need API key URLs."""
        # These providers don't require API keys
        assert PROVIDER_API_KEY_URLS.get("public") is None
        assert PROVIDER_API_KEY_URLS.get("ollama") is None


class TestValidateProviderName:
    """Tests for provider name validation."""

    def test_valid_providers(self) -> None:
        """All valid provider names should return AIProvider enum."""
        for provider in AIProvider:
            result = validate_provider_name(provider.value)
            assert result == provider

    def test_case_insensitive(self) -> None:
        """Provider names should be case-insensitive."""
        assert validate_provider_name("OPENAI") == AIProvider.OPENAI
        assert validate_provider_name("OpenAI") == AIProvider.OPENAI
        assert validate_provider_name("openai") == AIProvider.OPENAI

    def test_invalid_provider(self) -> None:
        """Invalid provider names should return None."""
        assert validate_provider_name("invalid") is None
        assert validate_provider_name("") is None
        assert validate_provider_name("unknown_provider") is None


class TestGetValidProviderNames:
    """Tests for getting valid provider name list."""

    def test_returns_all_providers(self) -> None:
        """Returns list of all provider name strings."""
        names = get_valid_provider_names()
        assert len(names) == len(AIProvider)
        for provider in AIProvider:
            assert provider.value in names


class TestMaskApiKey:
    """Tests for API key masking."""

    def test_mask_standard_key(self) -> None:
        """Standard API key is properly masked."""
        result = mask_api_key("sk-1234567890abcdef")
        assert result == "sk-1***def"
        assert "1234567890abcd" not in result

    def test_mask_short_key(self) -> None:
        """Short keys are fully masked."""
        result = mask_api_key("short")
        assert result == "*****"
        assert "short" not in result

    def test_mask_very_short_key(self) -> None:
        """Very short keys are fully masked."""
        result = mask_api_key("abc")
        assert result == "***"

    def test_mask_empty_key(self) -> None:
        """Empty key returns empty mask."""
        result = mask_api_key("")
        assert result == ""
