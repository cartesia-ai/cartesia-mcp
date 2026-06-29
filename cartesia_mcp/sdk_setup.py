"""Configure the Fern Cartesia client for MCP (API version, shared HTTP)."""

from __future__ import annotations

from cartesia import Cartesia
from cartesia.core.http_client import HttpClient

from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.client_headers import client_request_headers, user_agent

# Admin keys use sk_car_admin_<id>.<secret>; standard keys use sk_car_<id>.<secret>.
ADMIN_API_KEY_PREFIX = "sk_car_admin_"

_v2_websocket_headers_patched = False


def is_admin_api_key(api_key: str) -> bool:
    return api_key.startswith(ADMIN_API_KEY_PREFIX)


def create_cartesia_client(api_key: str) -> Cartesia:
    _patch_v2_websocket_client_headers()
    client = Cartesia(api_key=api_key)
    _apply_api_version(client._client_wrapper)
    return client


def get_http(client: Cartesia) -> HttpClient:
    return client._client_wrapper.httpx_client


def _patch_v2_websocket_client_headers() -> None:
    """SDK v2 STT WebSocket uses websockets.sync without httpx headers."""
    global _v2_websocket_headers_patched
    if _v2_websocket_headers_patched:
        return

    from websockets.sync import client as ws_sync_client

    original_connect = ws_sync_client.connect

    def connect_with_mcp_headers(uri, *args, **kwargs):
        additional_headers = dict(kwargs.pop("additional_headers", None) or {})
        additional_headers.update(client_request_headers())
        return original_connect(
            uri,
            *args,
            user_agent_header=kwargs.pop("user_agent_header", user_agent()),
            additional_headers=additional_headers,
            **kwargs,
        )

    ws_sync_client.connect = connect_with_mcp_headers
    _v2_websocket_headers_patched = True


def _apply_api_version(wrapper) -> None:
    original_get_headers = wrapper.get_headers

    def get_headers() -> dict[str, str]:
        headers = original_get_headers()
        headers["Cartesia-Version"] = CARTESIA_VERSION
        headers.update(client_request_headers())
        return headers

    wrapper.get_headers = get_headers
    # HttpClient stores base_headers at init; refresh so extra_api routes pick up the version.
    wrapper.httpx_client.base_headers = wrapper.get_headers
