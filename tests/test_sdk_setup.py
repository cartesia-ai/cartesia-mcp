"""Tests for Cartesia SDK v3 client setup."""

from __future__ import annotations

from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.client_headers import client_request_headers
from cartesia_mcp.sdk_setup import create_cartesia_client


def test_create_cartesia_client_sets_default_headers() -> None:
    client = create_cartesia_client("sk_car_test_key")

    headers = client.default_headers
    assert headers["cartesia-version"] == CARTESIA_VERSION
    assert headers["User-Agent"] == client_request_headers()["User-Agent"]
    assert headers["X-Cartesia-Client"] == client_request_headers()["X-Cartesia-Client"]
