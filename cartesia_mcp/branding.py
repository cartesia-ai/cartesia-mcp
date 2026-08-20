"""Server identity and brand assets advertised to MCP clients."""

from __future__ import annotations

from pathlib import Path

from mcp.types import Icon

SERVER_NAME = "Cartesia"
SERVER_DESCRIPTION = "The official Cartesia MCP server"
WEBSITE_URL = "https://cartesia.ai"
PRODUCTION_MCP_ORIGIN = "https://mcp.cartesia.ai"
ICON_PATH = "/icon.png"
ICON_SIZES = ["512x512"]

STATIC_DIR = Path(__file__).resolve().parent / "static"
ICON_PNG_PATH = STATIC_DIR / "icon.png"


def icon_url(origin: str | None = None) -> str:
    base = (origin or PRODUCTION_MCP_ORIGIN).rstrip("/")
    return f"{base}{ICON_PATH}"


def server_icons(*, origin: str | None = None) -> list[Icon]:
    return [
        Icon(
            src=icon_url(origin),
            mime_type="image/png",
            sizes=ICON_SIZES,
        )
    ]
