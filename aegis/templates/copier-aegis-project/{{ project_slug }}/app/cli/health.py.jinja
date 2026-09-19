"""
Health monitoring CLI commands.

Command-line interface for system health checking and monitoring via API endpoints.
"""

import asyncio
import json
import sys

import httpx
import typer

from app.cli import theme
from app.cli.health_display import _display_health_status
from app.core.config import settings
from app.core.constants import APIEndpoints, Defaults
from app.core.log import setup_logging
from app.i18n import lazy_t, t
from app.services.system.models import (
    DetailedHealthResponse,
    HealthResponse,
)

app = typer.Typer(name="health", help=lazy_t("health.help"))
console = theme.console()

# Pattern-based translation for health API response messages.
# Maps English substrings/prefixes to i18n keys for display-time translation.


async def get_health_data(
    endpoint: str = APIEndpoints.HEALTH_BASIC,
) -> HealthResponse | DetailedHealthResponse:
    """Get health data from the API endpoint with Pydantic validation."""
    base_url = getattr(settings, "API_BASE_URL", "http://localhost:8000")
    url = f"{base_url}{endpoint}"

    timeout = httpx.Timeout(Defaults.API_TIMEOUT)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            json_data = response.json()

            # Validate response with appropriate Pydantic model
            if endpoint == APIEndpoints.HEALTH_DETAILED:
                return DetailedHealthResponse.model_validate(json_data)
            else:
                return HealthResponse.model_validate(json_data)

        except httpx.ConnectError:
            raise ConnectionError(t("health.connect_error", url=base_url)) from None
        except httpx.TimeoutException:
            raise TimeoutError(
                t("health.timeout_error", url=url, timeout=Defaults.API_TIMEOUT)
            ) from None
        except httpx.HTTPStatusError as e:
            # Handle structured error responses from health endpoint
            if e.response.status_code == 503:
                try:
                    error_data = e.response.json()
                    if "detail" in error_data and isinstance(
                        error_data["detail"], dict
                    ):
                        detail = error_data["detail"]
                        message = detail.get("message", t("health.system_unhealthy"))
                        unhealthy_components = detail.get("unhealthy_components", [])
                        health_percentage = detail.get("health_percentage", 0)

                        error_msg = f"{message}"
                        if unhealthy_components:
                            components_str = ", ".join(unhealthy_components)
                            unhealthy = t(
                                "health.unhealthy_label",
                                components=components_str,
                            )
                            error_msg += f" ({unhealthy})"
                        if health_percentage is not None:
                            pct_label = t(
                                "health.health_pct_label",
                                pct=f"{health_percentage:.1f}%",
                            )
                            error_msg += f" - {pct_label}"

                        raise RuntimeError(error_msg) from None
                except (ValueError, KeyError, TypeError):
                    # Fall back to generic error message if JSON parsing fails
                    pass

            raise RuntimeError(
                t(
                    "health.api_error",
                    status=e.response.status_code,
                    text=e.response.text,
                )
            ) from None


async def is_system_healthy() -> bool:
    """Quick check if system is healthy via API."""
    try:
        health_data = await get_health_data(APIEndpoints.HEALTH_BASIC)
        return health_data.healthy
    except Exception:
        return False


@app.command("status", help=lazy_t("health.help_status"))
def health_status(
    detailed: bool = typer.Option(
        False, "--detailed", "-d", help=lazy_t("health.opt_detailed")
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j", help=lazy_t("health.opt_json")
    ),
) -> None:
    setup_logging()

    try:
        endpoint = (
            APIEndpoints.HEALTH_DETAILED if detailed else APIEndpoints.HEALTH_BASIC
        )
        health_data = asyncio.run(get_health_data(endpoint))

        if json_output:
            print(json.dumps(health_data.model_dump(), indent=2))
        else:
            _display_health_status(health_data, detailed)

        # Always exit 0 for status command (informational)

    except Exception as e:
        if json_output:
            error_data = {"error": str(e), "status": "error"}
            print(json.dumps(error_data, indent=2))
        else:
            console.print(f"[{theme.ERROR}]{t('health.status_failed', error=e)}[/]")
        # Exit 1 only on actual errors (connection failures, etc), not unhealthy status
        sys.exit(1)


@app.command("probe", help=lazy_t("health.help_probe"))
def health_probe() -> None:
    setup_logging()

    try:
        healthy = asyncio.run(is_system_healthy())

        if healthy:
            console.print(f"[{theme.ACCENT}]{t('health.system_healthy')}[/]")
            sys.exit(0)
        else:
            console.print(f"[{theme.ERROR}]{t('health.system_unhealthy_msg')}[/]")
            sys.exit(1)

    except Exception as e:
        console.print(f"[{theme.ERROR}]{t('health.probe_failed', error=e)}[/]")
        sys.exit(1)


if __name__ == "__main__":
    app()
