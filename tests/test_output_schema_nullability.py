"""Fail CI if any tool output schema has default=null without allowing null.

FastMCP converts optional TypedDict fields to Pydantic fields with default=None
and dumps unset keys as null. Clients then validate structuredContent against
outputSchema — so ``type: string, default: null`` hard-fails at runtime.
"""

from __future__ import annotations

import asyncio
from typing import Any

import cartesia_mcp.server as server


def _allows_null(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "null":
        return True
    for alt in schema.get("anyOf", []) + schema.get("oneOf", []):
        if isinstance(alt, dict) and alt.get("type") == "null":
            return True
    return False


def _bad_null_defaults(schema: dict[str, Any], path: str = "$") -> list[str]:
    issues: list[str] = []
    if not isinstance(schema, dict):
        return issues

    if "default" in schema and schema["default"] is None and not _allows_null(schema):
        issues.append(f"{path}: default=null but type does not allow null ({schema.get('type')!r})")

    for name, prop in schema.get("properties", {}).items():
        if isinstance(prop, dict):
            issues.extend(_bad_null_defaults(prop, f"{path}.{name}"))

    items = schema.get("items")
    if isinstance(items, dict):
        issues.extend(_bad_null_defaults(items, f"{path}[]"))

    for name, defn in schema.get("$defs", {}).items():
        if isinstance(defn, dict):
            issues.extend(_bad_null_defaults(defn, f"{path}.$defs.{name}"))

    return issues


def test_all_tool_output_schemas_allow_null_defaults() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    failures: list[str] = []
    for tool in tools:
        if tool.outputSchema is None:
            continue
        for issue in _bad_null_defaults(tool.outputSchema):
            failures.append(f"{tool.name}: {issue}")
    assert failures == [], "Invalid output schemas:\n" + "\n".join(failures)
