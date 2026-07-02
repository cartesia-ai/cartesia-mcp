"""Cartesia FastMCP server with session-aware tool listing."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool

from cartesia_mcp.tool_visibility import is_tool_visible


class CartesiaMCP(FastMCP):
    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        return [tool for tool in tools if is_tool_visible(tool.name)]
