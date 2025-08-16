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


