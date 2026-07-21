"""
Application constants.

This module contains truly immutable values that never change across environments.
For environment-dependent configuration, see app.core.config.

Following 12-Factor App principles:
- Constants = code (version controlled, immutable across deployments)
- Configuration = environment (varies between dev/staging/production)
"""


class APIEndpoints:
    """API endpoint paths - immutable across all environments."""

    HEALTH_BASIC = "/health/"
    HEALTH_DETAILED = "/health/detailed"
    HEALTH_DASHBOARD = "/health/dashboard"
    AI_USAGE_STATS = "/ai/usage/stats"
    AI_SENTIMENT_STATS = "/ai/sentiment/stats"


class Defaults:
    """Default values for timeouts and limits."""

    # API timeouts (seconds)
    API_TIMEOUT = 10.0
    HEALTH_CHECK_TIMEOUT = 5.0

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF = 1.0

    # Health check intervals (seconds)
    HEALTH_CHECK_INTERVAL = 30
    COMPONENT_CHECK_TIMEOUT = 2.0


def country_flag(code: str) -> str:
    """Convert 2-letter ISO country code to flag emoji."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


def _cn(code: str, name: str) -> tuple[str, str]:
    return code, f"{country_flag(code)} {name}"


COUNTRY_NAMES: dict[str, str] = dict(
    [
        _cn("US", "United States"),
        _cn("GB", "United Kingdom"),
        _cn("DE", "Germany"),
        _cn("FR", "France"),
        _cn("IN", "India"),
        _cn("CN", "China"),
        _cn("JP", "Japan"),
        _cn("BR", "Brazil"),
        _cn("CA", "Canada"),
        _cn("AU", "Australia"),
        _cn("RU", "Russia"),
        _cn("KR", "South Korea"),
        _cn("ES", "Spain"),
        _cn("IT", "Italy"),
        _cn("NL", "Netherlands"),
        _cn("SE", "Sweden"),
        _cn("MX", "Mexico"),
        _cn("PL", "Poland"),
        _cn("TW", "Taiwan"),
        _cn("TH", "Thailand"),
        _cn("ID", "Indonesia"),
        _cn("TR", "Turkey"),
        _cn("CH", "Switzerland"),
        _cn("AR", "Argentina"),
        _cn("CO", "Colombia"),
        _cn("VN", "Vietnam"),
        _cn("PH", "Philippines"),
        _cn("EG", "Egypt"),
        _cn("ZA", "South Africa"),
        _cn("UY", "Uruguay"),
        _cn("PE", "Peru"),
        _cn("CL", "Chile"),
        _cn("SG", "Singapore"),
        _cn("MY", "Malaysia"),
        _cn("HK", "Hong Kong"),
        _cn("IL", "Israel"),
        _cn("NO", "Norway"),
        _cn("DK", "Denmark"),
        _cn("FI", "Finland"),
        _cn("AT", "Austria"),
        _cn("BE", "Belgium"),
        _cn("PT", "Portugal"),
        _cn("CZ", "Czechia"),
        _cn("RO", "Romania"),
        _cn("UA", "Ukraine"),
        _cn("NG", "Nigeria"),
        _cn("KE", "Kenya"),
        _cn("PK", "Pakistan"),
        _cn("BD", "Bangladesh"),
        _cn("SA", "Saudi Arabia"),
        _cn("IE", "Ireland"),
        _cn("NZ", "New Zealand"),
        _cn("GR", "Greece"),
        _cn("HU", "Hungary"),
    ]
)


class CLI:
    """CLI-specific constants."""

    # Display limits
    MAX_METADATA_DISPLAY_LENGTH = 30

    # Output formatting
    HEALTH_PERCENTAGE_DECIMALS = 1
    TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class HTTP:
    """HTTP-related constants."""

    # Status codes we care about
    OK = 200
    SERVICE_UNAVAILABLE = 503
    INTERNAL_SERVER_ERROR = 500

    # Headers
    CONTENT_TYPE_JSON = "application/json"
    USER_AGENT = "AegisStack-CLI/1.0"
