"""Outbound API request attribution for cartesia-mcp."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

CLIENT_NAME = "cartesia-mcp"


def get_package_version() -> str:
    try:
        return version("cartesia-mcp")
    except PackageNotFoundError:
        return "0.0.0.dev"


def client_request_headers() -> dict[str, str]:
    """Headers attached to every Cartesia API call from this MCP server."""
    ver = get_package_version()
    return {
        "X-Cartesia-Client": CLIENT_NAME,
        "X-Cartesia-Client-Version": ver,
        "User-Agent": f"{CLIENT_NAME}/{ver}",
    }
