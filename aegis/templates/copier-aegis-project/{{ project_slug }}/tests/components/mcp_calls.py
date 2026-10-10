"""The MCP tests' recorder: pass it as ``build_server(record=...)`` (or in
place of ``http.record``) and read back the calls it kept."""

from app.components.mcp.server import McpCall


class Recorder(list[McpCall]):
    async def __call__(self, call: McpCall) -> None:
        self.append(call)
