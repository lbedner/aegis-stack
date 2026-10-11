"""Every compose service declares the profiles it runs under.

`make serve` and `make serve-prod` pick services by profile. A service with
none starts under every invocation instead, including ones meant to leave
it out; the browser shipped that way.
"""

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_every_service_names_its_profiles() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]

    missing = [name for name, spec in services.items() if not spec.get("profiles")]

    assert not missing, f"no profiles: {missing}"
