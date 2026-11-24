"""Inline MCP App player for `text_to_speech` results."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from mcp.server.apps import Apps, ResourceCsp, ResourcePermissions

TTS_PLAYER_URI = "ui://cartesia/tts-player.html"

# Hosts seen on live `download_url` HEADs (no 302). Keep in sync with storage.
_AUDIO_ORIGINS = [
    "https://files.cartesia.ai",
]


def load_tts_player_html() -> str:
    """Return the bundled player HTML from package data."""
    try:
        return (
            resources.files("cartesia_mcp")
            .joinpath("static/tts-player.html")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, TypeError, OSError):
        path = Path(__file__).resolve().parent / "static" / "tts-player.html"
        return path.read_text(encoding="utf-8")


def create_tts_player_apps() -> Apps:
    """Apps extension that serves the TTS player UI resource."""
    apps = Apps()
    apps.add_html_resource(
        TTS_PLAYER_URI,
        load_tts_player_html(),
        name="cartesia-tts-player",
        title="Cartesia TTS Player",
        description="Inline player for text_to_speech results.",
        csp=ResourceCsp(
            resource_domains=[*_AUDIO_ORIGINS],
            connect_domains=[*_AUDIO_ORIGINS],
        ),
        permissions=ResourcePermissions(clipboard_write={}),
        prefers_border=True,
    )
    return apps


def text_to_speech_ui_meta() -> dict:
    """Tool `_meta` that binds `text_to_speech` to the player resource."""
    return {
        "ui": {"resourceUri": TTS_PLAYER_URI},
        # Legacy key for older hosts.
        "ui/resourceUri": TTS_PLAYER_URI,
    }
