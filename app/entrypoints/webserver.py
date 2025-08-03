#!/usr/bin/env python3
"""
Web server entry point for Aegis Stack.
Runs FastAPI + Flet only (clean separation of concerns).
"""

import uvicorn

from app.core.log import logger, setup_logging
from app.integrations.main import create_integrated_app


def main() -> None:
    """Main webserver entry point"""
    setup_logging()
    logger.info("Starting Aegis Stack Web Server...")

    # Use the integration layer (handles lifecycle, service discovery, etc.)
    app = create_integrated_app()

    # Run the web server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_config=None,  # Use our structured logging
    )


if __name__ == "__main__":
    main()
