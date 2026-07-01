"""Configure the Cartesia Python SDK v3 client for MCP."""

from __future__ import annotations

from cartesia import Cartesia

from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.client_headers import client_request_headers

# Admin keys use sk_car_admin_<id>.<secret>; standard keys use sk_car_<id>.<secret>.
ADMIN_API_KEY_PREFIX = "sk_car_admin_"


def is_admin_api_key(api_key: str) -> bool:
    return api_key.startswith(ADMIN_API_KEY_PREFIX)


def create_cartesia_client(api_key: str) -> Cartesia:
    return Cartesia(
        api_key=api_key,
        default_headers={
            "cartesia-version": CARTESIA_VERSION,
            **client_request_headers(),
        },
    )
