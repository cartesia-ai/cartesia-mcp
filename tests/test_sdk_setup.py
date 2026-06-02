"""Tests for Cartesia client header wiring in sdk_setup."""

from __future__ import annotations

from unittest.mock import MagicMock

from cartesia_mcp.api_version import CARTESIA_VERSION
from cartesia_mcp.client_headers import user_agent
from cartesia_mcp.sdk_setup import _apply_api_version


def test_apply_api_version_sets_mcp_user_agent() -> None:
    wrapper = MagicMock()
    wrapper.get_headers.return_value = {
        "X-Fern-Language": "Python",
        "X-Fern-SDK-Name": "cartesia",
        "X-Fern-SDK-Version": "2.0.17",
    }
    wrapper.httpx_client = MagicMock()

    _apply_api_version(wrapper)

    headers = wrapper.get_headers()
    assert headers["Cartesia-Version"] == CARTESIA_VERSION
    assert headers["User-Agent"] == user_agent()
    assert wrapper.httpx_client.base_headers == wrapper.get_headers
