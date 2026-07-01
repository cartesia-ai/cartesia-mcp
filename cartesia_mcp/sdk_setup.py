"""Configure the Cartesia Python SDK v3 client for MCP."""

from __future__ import annotations

from cartesia import Cartesia

from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.client_headers import client_request_headers

# Admin keys use sk_car_admin_<id>.<secret>; standard keys use sk_car_<id>.<secret>.
ADMIN_API_KEY_PREFIX = "sk_car_admin_"


def is_admin_api_key(api_key: str) -> bool:
    return api_key.startswith(ADMIN_API_KEY_PREFIX)


def _looks_like_cartesia_access_token(credential: str) -> bool:
    return credential.startswith("eyJ")


def create_cartesia_client(credential: str) -> Cartesia:
    headers = {
        "cartesia-version": CARTESIA_VERSION,
        **client_request_headers(),
    }
    if _looks_like_cartesia_access_token(credential):
        return Cartesia(token=credential, default_headers=headers)
    return Cartesia(api_key=credential, default_headers=headers)
