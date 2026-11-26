"""MCP App binding for the text_to_speech player."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mcp.client import Client
from mcp.client.extension import advertise

import cartesia_mcp.server as server
from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.constants import DEFAULT_MODEL_ID
from cartesia_mcp.tts_player import TTS_PLAYER_URI, load_tts_player_html

APPS_EXTENSION = advertise(
    "io.modelcontextprotocol/ui",
    {"mimeTypes": ["text/html;profile=mcp-app"]},
)


def test_tts_player_html_is_self_contained() -> None:
    html = load_tts_player_html()
    assert "Cartesia TTS" in html
    assert "api.cartesia.ai/tts/bytes" in html
    # The MCP Apps bridge is bundled in, so hosts need no script CDN.
    assert not re.search(r"<script[^>]+src=", html)
    assert "unpkg.com" not in html
    assert not re.search(r"""\bfrom\s*["']https?://""", html)


def test_text_to_speech_advertises_ui_resource() -> None:
    tools = asyncio.run(server.mcp.list_tools())
    tts = next(tool for tool in tools if tool.name == "text_to_speech")
    assert tts.meta is not None
    assert tts.meta.get("ui", {}).get("resourceUri") == TTS_PLAYER_URI
    assert tts.meta.get("ui/resourceUri") == TTS_PLAYER_URI
    # ctx is injected by the SDK, never part of the tool's input schema.
    assert "ctx" not in tts.input_schema["properties"]


def test_tts_player_resource_is_mcp_app_html() -> None:
    resources = asyncio.run(server.mcp.list_resources())
    player = next(
        resource for resource in resources if str(resource.uri) == TTS_PLAYER_URI
    )
    assert player.mime_type == "text/html;profile=mcp-app"
    assert player.meta is not None
    csp = player.meta.get("ui", {}).get("csp", {})
    assert csp.get("resourceDomains") == ["https://files.cartesia.ai"]
    assert csp.get("connectDomains") == ["https://files.cartesia.ai"]


def test_default_model_is_the_latest_alias() -> None:
    assert DEFAULT_MODEL_ID == "sonic-latest"


async def _generate(
    tmp_path: Path,
    *,
    mode: str,
    apps: bool,
) -> dict[str, object]:
    extensions = [APPS_EXTENSION] if apps else None
    async with Client(server.mcp, mode=mode, extensions=extensions) as client:  # type: ignore[arg-type]
        result = await client.call_tool(
            "text_to_speech",
            {
                "transcript": "Hello",
                "voice_id": "voice_abc",
                "output_format": {
                    "container": "wav",
                    "encoding": "pcm_s16le",
                    "sample_rate": 44100,
                },
                "language": "fr",
                "volume": 1.5,
                "output_path": str(tmp_path / "clip.wav"),
                "save": False,
            },
        )
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
@patch("cartesia_mcp.mcp_app.client")
def test_apps_clients_get_the_request_back(
    mock_client: MagicMock, tmp_path: Path, mode: str
) -> None:
    mock_client.tts.generate.return_value = MagicMock(read=lambda: b"audio", headers={})

    result = asyncio.run(_generate(tmp_path, mode=mode, apps=True))

    assert result["transcript"] == "Hello"
    assert result["voice_id"] == "voice_abc"
    assert result["model_id"] == DEFAULT_MODEL_ID
    assert result["language"] == "fr"
    assert result["volume"] == 1.5
    assert result["cartesia_version"] == CARTESIA_VERSION
    assert "emotion" not in result


@patch("cartesia_mcp.mcp_app.client")
def test_other_clients_keep_the_lean_response(
    mock_client: MagicMock, tmp_path: Path
) -> None:
    mock_client.tts.generate.return_value = MagicMock(read=lambda: b"audio", headers={})

    result = asyncio.run(_generate(tmp_path, mode="legacy", apps=False))

    # Structured output omits unset keys; the player treats missing and null alike.
    assert {key for key, value in result.items() if value is not None} == {"file_path"}
