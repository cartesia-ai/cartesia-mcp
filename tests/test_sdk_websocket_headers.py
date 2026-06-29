"""Tests for SDK v2 WebSocket client attribution headers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cartesia_mcp.client_headers import client_request_headers, user_agent
from cartesia_mcp.sdk_setup import _patch_v2_websocket_client_headers


def test_patch_v2_websocket_client_headers_stamps_connect(monkeypatch) -> None:
    import cartesia_mcp.sdk_setup as sdk_setup

    sdk_setup._v2_websocket_headers_patched = False

    captured: dict = {}

    def fake_connect(uri, *args, **kwargs):
        captured["uri"] = uri
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)

    _patch_v2_websocket_client_headers()

    from websockets.sync import client as ws_sync_client

    ws_sync_client.connect("wss://api.cartesia.ai/stt/websocket")

    assert captured["kwargs"]["user_agent_header"] == user_agent()
    assert captured["kwargs"]["additional_headers"] == client_request_headers()

    sdk_setup._v2_websocket_headers_patched = False
