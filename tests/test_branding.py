"""Tests for MCP server brand metadata and hosted icon routes."""

from __future__ import annotations

import struct

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp import __version__
from cartesia_mcp.branding import (
    ICON_PNG_PATH,
    ICON_SVG_FILE,
    PRODUCTION_MCP_ORIGIN,
    SERVER_DESCRIPTION,
    SERVER_NAME,
    WEBSITE_URL,
    icon_url,
    server_icons,
)
from cartesia_mcp.hosted import icon_png, icon_svg, index
from cartesia_mcp.mcpserver import CartesiaMCP
from cartesia_mcp.server import mcp


def test_icon_png_is_packaged_512_square() -> None:
    data = ICON_PNG_PATH.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (512, 512)


def test_icon_url_defaults_to_production() -> None:
    assert icon_url() == f"{PRODUCTION_MCP_ORIGIN}/icon.png"


def test_icon_url_uses_hosted_origin(monkeypatch) -> None:
    monkeypatch.setenv("MCP_SERVER_URL", "https://mcp.example.test")
    from cartesia_mcp.hosted import server_public_url

    assert icon_url(server_public_url()) == "https://mcp.example.test/icon.png"


def test_server_icons_shape() -> None:
    png, svg = server_icons()
    assert png.src == f"{PRODUCTION_MCP_ORIGIN}/icon.png"
    assert png.mime_type == "image/png"
    assert png.sizes == ["512x512"]
    assert svg.src == f"{PRODUCTION_MCP_ORIGIN}/icon.svg"
    assert svg.mime_type == "image/svg+xml"
    assert svg.sizes == ["any"]


def test_stdio_server_advertises_brand() -> None:
    assert mcp.name == SERVER_NAME
    assert mcp.description == SERVER_DESCRIPTION
    assert mcp.website_url == WEBSITE_URL
    assert mcp.version == __version__
    assert mcp.icons == server_icons()


def test_hosted_icon_origin_on_server_construction() -> None:
    icons = server_icons(origin="https://mcp.cartesia.ai")
    hosted = CartesiaMCP(
        SERVER_NAME,
        description=SERVER_DESCRIPTION,
        website_url=WEBSITE_URL,
        icons=icons,
        version=__version__,
    )
    assert hosted.icons == icons


def _icon_client() -> TestClient:
    return TestClient(
        Starlette(
            routes=[
                Route("/icon.png", endpoint=icon_png, methods=["GET"]),
                Route("/favicon.ico", endpoint=icon_png, methods=["GET"]),
                Route("/icon.svg", endpoint=icon_svg, methods=["GET"]),
                Route("/", endpoint=index, methods=["GET"]),
            ]
        )
    )


def test_icon_png_route_serves_png() -> None:
    response = _icon_client().get("/icon.png")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == ICON_PNG_PATH.read_bytes()
    assert "max-age=86400" in response.headers["cache-control"]


def test_favicon_route_serves_same_png() -> None:
    response = _icon_client().get("/favicon.ico")
    assert response.status_code == 200
    assert response.content == ICON_PNG_PATH.read_bytes()


def test_icon_svg_route_serves_svg() -> None:
    response = _icon_client().get("/icon.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.content == ICON_SVG_FILE.read_bytes()


def test_index_links_icons_for_favicon_scrapers() -> None:
    response = _icon_client().get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<link rel="icon" href="/icon.svg" type="image/svg+xml">' in response.text
    assert '<link rel="icon" href="/icon.png"' in response.text
    assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png">' in response.text
