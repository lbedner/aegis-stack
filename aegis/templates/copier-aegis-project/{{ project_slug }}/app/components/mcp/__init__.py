"""MCP: an outside assistant reads the app through its own tools.

``<app> mcp`` serves the granted tools (``settings.MCP_TOOLS``) over stdio
to a local client: Claude Desktop, Claude Code, a local model. Whoever can
run the CLI already owns the database, so stdio needs no token.
"""
