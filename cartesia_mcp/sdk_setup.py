"""Configure the Fern Cartesia client for MCP (API version, shared HTTP)."""

from __future__ import annotations

from cartesia import Cartesia
from cartesia.core.http_client import HttpClient

from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.client_headers import client_request_headers

# Admin keys use sk_car_admin_<id>.<secret>; standard keys use sk_car_<id>.<secret>.
ADMIN_API_KEY_PREFIX = "sk_car_admin_"


def is_admin_api_key(api_key: str) -> bool:
    return api_key.startswith(ADMIN_API_KEY_PREFIX)


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
        headers.update(client_request_headers())
        return headers

    wrapper.get_headers = get_headers
    # HttpClient stores base_headers at init; refresh so extra_api routes pick up the version.
    wrapper.httpx_client.base_headers = wrapper.get_headers
