"""Tests for outbound client attribution headers."""

from __future__ import annotations

from cartesia_mcp.client_headers import CLIENT_NAME, client_request_headers, get_package_version


def test_get_package_version_is_non_empty() -> None:
    assert get_package_version()


def test_client_request_headers() -> None:
    headers = client_request_headers()
    ver = get_package_version()

    assert headers["X-Cartesia-Client"] == CLIENT_NAME
    assert headers["X-Cartesia-Client-Version"] == ver
    assert headers["User-Agent"] == f"{CLIENT_NAME}/{ver}"
