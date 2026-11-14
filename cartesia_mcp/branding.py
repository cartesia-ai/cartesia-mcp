"""Server identity and brand assets advertised to MCP clients."""

from __future__ import annotations

from pathlib import Path

from mcp.types import Icon

SERVER_NAME = "Cartesia"
SERVER_DESCRIPTION = "The official Cartesia MCP server"
WEBSITE_URL = "https://cartesia.ai"
PRODUCTION_MCP_ORIGIN = "https://mcp.cartesia.ai"
ICON_PATH = "/icon.png"
ICON_SVG_PATH = "/icon.svg"
ICON_SIZES = ["512x512"]
DOCS_URL = "https://docs.cartesia.ai/tools/ai/mcp"

STATIC_DIR = Path(__file__).resolve().parent / "static"
ICON_PNG_PATH = STATIC_DIR / "icon.png"
ICON_SVG_FILE = STATIC_DIR / "icon.svg"


def icon_url(origin: str | None = None, path: str = ICON_PATH) -> str:
    base = (origin or PRODUCTION_MCP_ORIGIN).rstrip("/")
    return f"{base}{path}"


def server_icons(*, origin: str | None = None) -> list[Icon]:
    return [
        Icon(
            src=icon_url(origin),
            mime_type="image/png",
            sizes=ICON_SIZES,
        ),
        Icon(
            src=icon_url(origin, ICON_SVG_PATH),
            mime_type="image/svg+xml",
            sizes=["any"],
        ),
    ]
