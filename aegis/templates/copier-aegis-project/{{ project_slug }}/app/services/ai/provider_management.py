"""
AI provider management utilities.

Provides functions for checking, installing, and configuring AI providers
at runtime, enabling users to dynamically add providers after project generation.
"""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from .models import AIProvider

# Provider to pydantic-ai-slim extras mapping
# Note: mistral, cohere, ollama, public, and pollinations use the
# OpenAI-compatible API
PROVIDER_DEPENDENCIES: dict[str, str] = {
    "openai": "pydantic-ai-slim[openai]",
    "anthropic": "pydantic-ai-slim[anthropic]",
    "google": "pydantic-ai-slim[google]",
    "groq": "pydantic-ai-slim[groq]",
    "mistral": "pydantic-ai-slim[openai]",
    "cohere": "pydantic-ai-slim[openai]",
    "ollama": "pydantic-ai-slim[openai]",
    "public": "pydantic-ai-slim[openai]",
    "pollinations": "pydantic-ai-slim[openai]",
}

# Actual SDK packages to check for each provider
# These are the real provider SDKs, not the pydantic-ai wrappers
PROVIDER_MODULE_CHECKS: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google.genai",  # google-genai package
    "groq": "groq",
    "mistral": "openai",  # Uses OpenAI-compatible API
    "cohere": "openai",  # Uses OpenAI-compatible API
    "ollama": "openai",  # Uses OpenAI-compatible API
    "public": "openai",  # Uses OpenAI-compatible API
    "pollinations": "openai",  # Uses OpenAI-compatible API
}

# API key documentation URLs for user guidance
PROVIDER_API_KEY_URLS: dict[str, str] = {
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/",
    "google": "https://aistudio.google.com/app/apikey",
    "groq": "https://console.groq.com/keys",
    "mistral": "https://console.mistral.ai/api-keys/",
    "cohere": "https://dashboard.cohere.com/api-keys",
}


def get_env_var_name(provider: str) -> str:
    """Get the environment variable name for a provider's API key.

    Args:
        provider: Provider name (e.g., "openai", "google")

    Returns:
        Environment variable name (e.g., "OPENAI_API_KEY", "GOOGLE_API_KEY")
    """
    return f"{provider.upper()}_API_KEY"


def check_provider_dependency_installed(provider: str) -> bool:
    """Check if the required pydantic-ai extra is installed for a provider.

    Uses importlib to check if the provider's model module can be found,
    indicating the required dependency is installed.

    Args:
        provider: Provider name to check

    Returns:
        True if the provider's dependency is installed, False otherwise
    """
    module_name = PROVIDER_MODULE_CHECKS.get(provider.lower())
    if not module_name:
        return False

    try:
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except (ModuleNotFoundError, ValueError):
        return False


def get_missing_dependency(provider: str) -> str | None:
    """Return the dependency package name if not installed.

    Args:
        provider: Provider name to check

    Returns:
        Package name to install, or None if already installed
    """
    if check_provider_dependency_installed(provider):
        return None
    return PROVIDER_DEPENDENCIES.get(provider.lower())


def install_provider_dependency(provider: str) -> tuple[bool, str]:
    """Install the provider dependency using uv or pip.

    Attempts to use uv first (preferred), then falls back to pip if uv
    is not available or fails.

    Args:
        provider: Provider name to install dependency for

    Returns:
        Tuple of (success, message) indicating result
    """
    dependency = PROVIDER_DEPENDENCIES.get(provider.lower())
    if not dependency:
        return False, f"Unknown provider: {provider}"

    # Try uv first (preferred)
    try:
        result = subprocess.run(
            ["uv", "add", dependency],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, f"Installed {dependency} with uv"
    except FileNotFoundError:
        # uv not available, will try pip
        pass
    except subprocess.TimeoutExpired:
        pass

    # Fall back to pip
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", dependency],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return True, f"Installed {dependency} with pip"
        return False, f"Failed to install {dependency}: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, f"Installation timed out for {dependency}"
    except Exception as e:
        return False, f"Failed to install {dependency}: {e}"


def read_env_file(env_path: Path | None = None) -> dict[str, str]:
    """Read .env file and return key-value pairs.

    Parses the .env file, ignoring comments and blank lines.

    Args:
        env_path: Path to .env file, defaults to .env in current directory

    Returns:
        Dictionary of environment variable key-value pairs
    """
    if env_path is None:
        env_path = Path(".env")

    result: dict[str, str] = {}

    if not env_path.exists():
        return result

    with open(env_path) as f:
        for line in f:
            stripped = line.strip()
            # Skip empty lines and comments
            if not stripped or stripped.startswith("#"):
                continue
            # Parse key=value
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove surrounding quotes if present
                if value and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                result[key] = value

    return result


def update_env_file(updates: dict[str, str], env_path: Path | None = None) -> None:
    """Update .env file with new values, preserving structure.

    Updates existing keys in place and appends new keys at the end.
    Preserves comments, blank lines, and formatting.

    Args:
        updates: Dictionary of key-value pairs to update/add
        env_path: Path to .env file, defaults to .env in current directory
    """
    if env_path is None:
        env_path = Path(".env")

    lines: list[str] = []
    updated_keys: set[str] = set()

    # Read existing file if it exists
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                stripped = line.strip()
                # Check if this is a key=value line (not comment)
                if "=" in stripped and not stripped.startswith("#"):
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        # Replace with new value
                        lines.append(f"{key}={updates[key]}\n")
                        updated_keys.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)

    # Add any new keys not already in the file
    for key, value in updates.items():
        if key not in updated_keys:
            # Add blank line before new keys if file doesn't end with one
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.append(f"{key}={value}\n")

    # Write back
    with open(env_path, "w") as f:
        f.writelines(lines)


def get_existing_api_key(provider: str, env_path: Path | None = None) -> str | None:
    """Check if API key already exists in .env or environment.

    Checks both the .env file and current environment variables.

    Args:
        provider: Provider name to check
        env_path: Path to .env file, defaults to .env in current directory

    Returns:
        API key value if found, None otherwise
    """
    env_var_name = get_env_var_name(provider)

    # First check environment variables (takes precedence)
    env_value = os.environ.get(env_var_name)
    if env_value:
        return env_value

    # Then check .env file
    env_vars = read_env_file(env_path)
    return env_vars.get(env_var_name)


def get_provider_api_key_url(provider: str) -> str | None:
    """Get the URL where users can obtain an API key for a provider.

    Args:
        provider: Provider name

    Returns:
        URL string or None if not available
    """
    return PROVIDER_API_KEY_URLS.get(provider.lower())


def validate_provider_name(provider: str) -> AIProvider | None:
    """Validate and convert provider name string to AIProvider enum.

    Args:
        provider: Provider name string to validate

    Returns:
        AIProvider enum value if valid, None if invalid
    """
    try:
        return AIProvider(provider.lower())
    except ValueError:
        return None


def get_valid_provider_names() -> list[str]:
    """Get list of valid provider names.

    Returns:
        List of valid provider name strings
    """
    return [p.value for p in AIProvider]


def mask_api_key(api_key: str) -> str:
    """Mask an API key for safe display.

    Shows first 4 and last 4 characters, masks the rest.

    Args:
        api_key: Full API key string

    Returns:
        Masked API key (e.g., "sk-a***xyz")
    """
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}***{api_key[-3:]}"


__all__ = [
    "PROVIDER_DEPENDENCIES",
    "PROVIDER_API_KEY_URLS",
    "PROVIDER_MODULE_CHECKS",
    "get_env_var_name",
    "check_provider_dependency_installed",
    "get_missing_dependency",
    "install_provider_dependency",
    "read_env_file",
    "update_env_file",
    "get_existing_api_key",
    "get_provider_api_key_url",
    "validate_provider_name",
    "get_valid_provider_names",
    "mask_api_key",
]
