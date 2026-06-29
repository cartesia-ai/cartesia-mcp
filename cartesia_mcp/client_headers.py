"""Outbound API request attribution for cartesia-mcp."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

CLIENT_ID = "cartesia-mcp"


def get_package_version() -> str:
    try:
        return version("cartesia-mcp")
    except PackageNotFoundError:
        return "0.0.0.dev"


def client_header() -> str:
    return f"{CLIENT_ID}/{get_package_version()}"


def client_request_headers() -> dict[str, str]:
    """Headers attached to every Cartesia API call from this MCP server."""
    header = client_header()
    return {
        "User-Agent": header,
        "X-Cartesia-Client": header,
    }
