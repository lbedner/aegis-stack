"""The project's ``.env.example`` boots the app it is copied into."""

from pathlib import Path

from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_settings_accept_the_example() -> None:
    """Post-gen copies the example to ``.env``, and ``Settings`` forbids a
    key it does not declare: one there stops the app at import."""
    Settings(_env_file=ROOT / ".env.example")
