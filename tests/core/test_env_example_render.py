"""What ``.env.example`` may hold.

Post-gen copies it to ``.env``, and ``Settings`` forbids a key it does not
declare, so one meant for compose alone stops the app at import.
"""

from pathlib import Path

from aegis.core.template_cleanup import _active_env_keys
from tests.core._compose import render


def test_tls_settings_stay_out_of_the_apps_env(tmp_path: Path) -> None:
    """Compose reads these for production, from ``.env.deploy``."""
    env = tmp_path / ".env"
    env.write_text(
        render(
            ".env.example.jinja",
            include_ingress=True,
            ingress_tls=True,
            ingress_domain="app.example.org",
        )
    )

    assert not _active_env_keys(env) & {"DOMAIN", "ACME_EMAIL"}
