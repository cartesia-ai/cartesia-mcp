"""Configure the Fern Cartesia client for MCP (API version, shared HTTP)."""

from __future__ import annotations

from cartesia import Cartesia
from cartesia.core.http_client import HttpClient

from cartesia_mcp.api_version import CARTESIA_VERSION


def create_cartesia_client(api_key: str) -> Cartesia:
    client = Cartesia(api_key=api_key)
    _apply_api_version(client._client_wrapper)
    return client


def get_http(client: Cartesia) -> HttpClient:
    return client._client_wrapper.httpx_client


def _apply_api_version(wrapper) -> None:
    original_get_headers = wrapper.get_headers

    def get_headers() -> dict[str, str]:
        headers = original_get_headers()
        headers["Cartesia-Version"] = CARTESIA_VERSION
        return headers

    wrapper.get_headers = get_headers
    # HttpClient stores base_headers at init; refresh so extra_api routes pick up the version.
    wrapper.httpx_client.base_headers = wrapper.get_headers
