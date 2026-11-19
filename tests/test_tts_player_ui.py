"""MCP App binding for the text_to_speech audition player."""

from __future__ import annotations

import asyncio

import cartesia_mcp.server as server
from cartesia_mcp.tts_player import TTS_PLAYER_URI, load_tts_player_html


def test_tts_player_html_is_self_contained() -> None:
    html = load_tts_player_html()
    assert "Cartesia TTS" in html
    assert "Copy curl" in html
    assert "api.cartesia.ai/tts/bytes" in html
    assert "download_url" in html
    assert 'id="wave"' in html
    assert "requestAnimationFrame" in html
    assert "mask-image" in html
    assert "player-card" in html
    assert "afplay" not in html
    assert "play.cartesia.ai" not in html
    assert "is-playing" in html
    assert "Re-run" not in html
    assert 'id="emotion"' not in html


def test_text_to_speech_advertises_ui_resource() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    tts = next(tool for tool in tools if tool.name == "text_to_speech")
    assert tts.meta is not None
    assert tts.meta.get("ui", {}).get("resourceUri") == TTS_PLAYER_URI
    assert tts.meta.get("ui/resourceUri") == TTS_PLAYER_URI


def test_tts_player_resource_is_mcp_app_html() -> None:
    resources = asyncio.run(server.mcp.list_resources())
    player = next(
        resource for resource in resources if str(resource.uri) == TTS_PLAYER_URI
    )
    assert player.mime_type == "text/html;profile=mcp-app"
    assert player.meta is not None
    csp = player.meta.get("ui", {}).get("csp", {})
    assert "https://files.cartesia.ai" in (csp.get("resourceDomains") or [])
