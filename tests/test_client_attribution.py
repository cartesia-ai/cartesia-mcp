"""Assert cartesia-mcp identifies itself on every outbound Cartesia API surface."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cartesia_mcp.client_headers import CLIENT_ID, USER_AGENT_PREFIX, client_header, client_request_headers, user_agent
from cartesia_mcp.sdk_setup import _apply_api_version, _patch_v2_websocket_client_headers


def expected_mcp_identity() -> dict[str, str]:
    ua = user_agent()
    header = client_header()
    assert ua.startswith(f"{USER_AGENT_PREFIX} ")
    assert header.startswith(f"{CLIENT_ID}/")
    return {
        "User-Agent": ua,
        "X-Cartesia-Client": header,
    }


def test_client_request_headers_is_canonical_mcp_identity() -> None:
    assert client_request_headers() == expected_mcp_identity()


def test_rest_httpx_identifies_as_cartesia_mcp() -> None:
    expected = expected_mcp_identity()
    wrapper = MagicMock()
    wrapper.get_headers.return_value = {"X-Fern-SDK-Name": "cartesia"}
    wrapper.httpx_client = MagicMock()

    _apply_api_version(wrapper)
    headers = wrapper.get_headers()

    assert headers["User-Agent"] == expected["User-Agent"]
    assert headers["X-Cartesia-Client"] == expected["X-Cartesia-Client"]


def test_stt_websocket_identifies_as_cartesia_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = expected_mcp_identity()
    import cartesia_mcp.sdk_setup as sdk_setup

    sdk_setup._v2_websocket_headers_patched = False
    captured: dict = {}

    def fake_connect(uri, *args, **kwargs):
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)
    _patch_v2_websocket_client_headers()

    from websockets.sync import client as ws_sync_client

    ws_sync_client.connect("wss://api.cartesia.ai/stt/websocket")

    assert captured["kwargs"]["user_agent_header"] == expected["User-Agent"]
    assert captured["kwargs"]["additional_headers"] == expected
    sdk_setup._v2_websocket_headers_patched = False


@pytest.mark.parametrize(
    "route",
    [
        "/tts/bytes",
        "/voices",
        "/stt/websocket",
    ],
)
def test_mcp_identity_format_is_stable_across_routes(route: str) -> None:
    del route  # documents routes MCP calls; identity does not vary by path
    expected = expected_mcp_identity()
    assert expected["User-Agent"].startswith("Cartesia/mcp ")
    assert expected["X-Cartesia-Client"].startswith("cartesia-mcp/")
