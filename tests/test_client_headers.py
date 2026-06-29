"""Tests for outbound client attribution headers."""

from __future__ import annotations

from cartesia_mcp.client_headers import CLIENT_ID, client_header, client_request_headers


def test_client_header_format() -> None:
    header = client_header()
    assert header.startswith(f"{CLIENT_ID}/")


def test_client_request_headers() -> None:
    header = client_header()
    headers = client_request_headers()
    assert headers == {
        "User-Agent": header,
        "X-Cartesia-Client": header,
    }
