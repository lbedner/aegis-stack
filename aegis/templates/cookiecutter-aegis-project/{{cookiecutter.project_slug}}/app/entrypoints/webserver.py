#!/usr/bin/env python3
"""
Web server entry point for Aegis Stack.
Runs FastAPI + Flet only (clean separation of concerns).
"""

import uvicorn

from app.core.config import settings
from app.core.log import logger, setup_logging
from app.integrations.main import create_integrated_app


def main() -> None:
    """Main webserver entry point"""
    setup_logging()
    logger.info("Starting Aegis Stack Web Server...")

    # Run the web server
    if settings.AUTO_RELOAD:
        # When reload is enabled, uvicorn requires an import string
        uvicorn.run(
            "app.integrations.main:create_integrated_app",
            factory=True,
            host="0.0.0.0",
            port=settings.PORT,
            reload=True,
        )
    else:
        # Use the integration layer (handles webserver hooks, service discovery, etc.)
        app = create_integrated_app()
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=settings.PORT,
        )


if __name__ == "__main__":
    main()
