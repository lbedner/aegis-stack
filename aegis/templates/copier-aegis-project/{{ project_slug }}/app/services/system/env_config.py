"""
Environment configuration service for reading and writing .env files.

Provides safe read/write operations for .env configuration files,
preserving comments, ordering, and formatting while allowing
dynamic updates to specific keys.
"""

import re
from pathlib import Path

from app.core.config import settings


class EnvConfigService:
    """
    Service for reading and writing .env configuration.

    Features:
    - Read all key-value pairs from .env file
    - Write/update specific keys while preserving file structure
    - Preserve comments, ordering, and empty lines
    - Dev mode detection for safe production environments
    """

    def __init__(self, env_path: Path | None = None) -> None:
        """
        Initialize the env config service.

        Args:
            env_path: Path to the .env file. Defaults to project root .env
        """
        if env_path is None:
            # Default to .env in project root (3 levels up from services/system/)
            self.env_path = Path(__file__).parents[3] / ".env"
        else:
            self.env_path = env_path

    def read_env(self) -> dict[str, str]:
        """
        Read all key-value pairs from .env file.

        Returns:
            Dictionary of environment variable names to values.
            Returns empty dict if file doesn't exist.
        """
        if not self.env_path.exists():
            return {}

        result: dict[str, str] = {}
        content = self.env_path.read_text(encoding="utf-8")

        for line in content.splitlines():
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Parse key=value pairs
            if "=" in line:
                # Handle KEY=VALUE, KEY="VALUE", KEY='VALUE'
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()

                # Remove surrounding quotes if present
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]

                result[key] = value

        return result

    def write_env(self, updates: dict[str, str]) -> None:
        """
        Update specific keys in .env file.

        Preserves:
        - Comments (lines starting with #)
        - Ordering of existing keys
        - Empty lines for readability
        - Keys that aren't being updated

        New keys are appended at the end of the file.

        Args:
            updates: Dictionary of key-value pairs to update/add
        """
        if not updates:
            return

        # Read existing content or start fresh
        if self.env_path.exists():
            lines = self.env_path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []

        # Track which keys we've updated
        updated_keys: set[str] = set()
        new_lines: list[str] = []

        # Process existing lines
        for line in lines:
            stripped = line.strip()

            # Keep comments and empty lines as-is
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue

            # Check if this line contains a key we need to update
            if "=" in stripped:
                key = stripped.split("=", 1)[0].strip()

                if key in updates:
                    # Replace with new value
                    value = updates[key]
                    # Quote value if it contains spaces or special chars
                    if self._needs_quoting(value):
                        new_lines.append(f'{key}="{value}"')
                    else:
                        new_lines.append(f"{key}={value}")
                    updated_keys.add(key)
                else:
                    # Keep original line
                    new_lines.append(line)
            else:
                # Keep non-matching lines
                new_lines.append(line)

        # Append any new keys that weren't in the file
        for key, value in updates.items():
            if key not in updated_keys:
                if self._needs_quoting(value):
                    new_lines.append(f'{key}="{value}"')
                else:
                    new_lines.append(f"{key}={value}")

        # Ensure file ends with newline
        content = "\n".join(new_lines)
        if content and not content.endswith("\n"):
            content += "\n"

        # Write atomically by writing to temp file then renaming
        temp_path = self.env_path.with_suffix(".env.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(self.env_path)

    def _needs_quoting(self, value: str) -> bool:
        """
        Check if a value needs to be quoted in .env file.

        Args:
            value: The value to check

        Returns:
            True if value should be quoted
        """
        if not value:
            return False

        # Quote if value contains spaces, special chars, or looks like it needs quotes
        needs_quotes = bool(
            re.search(r'[\s#"\']', value)
            or value.startswith(("$", "{"))
            or "=" in value
        )
        return needs_quotes

    def get_value(self, key: str) -> str | None:
        """
        Get a single value from .env file.

        Args:
            key: The environment variable name

        Returns:
            The value if found, None otherwise
        """
        env_vars = self.read_env()
        return env_vars.get(key)

    def is_dev_mode(self) -> bool:
        """
        Check if running in development mode.

        Development mode is determined by APP_ENV setting.
        Edit functionality should only be available in dev mode.

        Returns:
            True if APP_ENV is development/dev/local
        """
        return settings.is_dev
