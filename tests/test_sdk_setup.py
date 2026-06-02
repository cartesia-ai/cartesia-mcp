"""Tests for Cartesia client header wiring in sdk_setup."""

from __future__ import annotations

from unittest.mock import MagicMock

from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.client_headers import CLIENT_NAME, client_request_headers
from cartesia_mcp.sdk_setup import _apply_api_version


def test_apply_api_version_adds_mcp_client_headers() -> None:
    wrapper = MagicMock()
    wrapper.get_headers.return_value = {
        "X-Fern-Language": "Python",
        "X-Fern-SDK-Name": "cartesia",
        "X-Fern-SDK-Version": "2.0.17",
    }
    wrapper.httpx_client = MagicMock()

    _apply_api_version(wrapper)

    headers = wrapper.get_headers()
    expected = client_request_headers()

    assert headers["Cartesia-Version"] == CARTESIA_VERSION
    assert headers["X-Cartesia-Client"] == CLIENT_NAME
    assert headers["X-Cartesia-Client-Version"] == expected["X-Cartesia-Client-Version"]
    assert headers["User-Agent"] == expected["User-Agent"]
    assert wrapper.httpx_client.base_headers == wrapper.get_headers
