"""Cartesia MCP server with session-aware tool listing."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import Icon, Tool as MCPTool, ToolAnnotations

from cartesia_mcp.offload_sync import offload_sync_callable
from cartesia_mcp.tool_visibility import is_tool_visible


class CartesiaMCP(MCPServer):
    def add_tool(
        self,
        fn: Any,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        icons: list[Icon] | None = None,
        meta: dict[str, Any] | None = None,
        structured_output: bool | None = None,
    ) -> None:
        # Sync SDK tools must not block uvicorn's event loop (Render /health).
        super().add_tool(
            offload_sync_callable(fn),
            name=name,
            title=title,
            description=description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        return [tool for tool in tools if is_tool_visible(tool.name)]
