"""Cartesia MCP server with session-aware tool listing."""

from __future__ import annotations

import inspect
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import Icon, ToolAnnotations
from mcp.types import Tool as MCPTool

from cartesia_mcp.offload_sync import offload_sync_callable
from cartesia_mcp.tool_visibility import is_tool_visible


def compact_output_schema(schema: Any) -> Any:
    """Drop titles and string enums from an output schema; clients only need the shape.

    Output enums (accent ids, language codes) add kilobytes to every tool listing and
    reject values the API adds before the SDK catches up.
    """
    if isinstance(schema, list):
        return [compact_output_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title" and isinstance(value, str):
            continue
        if key == "enum" and schema.get("type") == "string":
            continue
        if key in ("properties", "$defs") and isinstance(value, dict):
            out[key] = {name: compact_output_schema(sub) for name, sub in value.items()}
        else:
            out[key] = compact_output_schema(value)
    for key in ("anyOf", "oneOf"):
        if key in out:
            unique: list[Any] = []
            for alt in out[key]:
                if alt not in unique:
                    unique.append(alt)
            if len(unique) == 1 and isinstance(unique[0], dict):
                del out[key]
                out.update(unique[0])
            else:
                out[key] = unique
    return out


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
            description=inspect.cleandoc(description) if description else description,
            annotations=annotations,
            icons=icons,
            meta=meta,
            structured_output=structured_output,
        )

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        return [
            tool.model_copy(update={"output_schema": compact_output_schema(tool.output_schema)})
            for tool in tools
            if is_tool_visible(tool.name)
        ]
