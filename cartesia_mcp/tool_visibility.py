"""Session-scoped visibility for admin-only MCP tools."""

from __future__ import annotations

from cartesia_mcp.credentials import resolve_admin_api_credential

ADMIN_ONLY_TOOLS = frozenset({"get_credit_usage"})


def admin_tools_available() -> bool:
    return resolve_admin_api_credential() is not None


def is_tool_visible(tool_name: str) -> bool:
    if tool_name in ADMIN_ONLY_TOOLS:
        return admin_tools_available()
    return True
