"""Keep this process's connection records alive (see
``middleware/connections.py``): a heartbeat the Server > Connections page
reads to tell a live connection from one a dead process left behind."""

from app.components.backend import background
from app.components.backend.middleware import connections

NAME = "connections_heartbeat"


async def startup_hook() -> None:
    background.start(NAME, connections.keep_alive())
