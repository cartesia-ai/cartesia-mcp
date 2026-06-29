"""Tests for outbound client attribution headers."""

from __future__ import annotations

from cartesia_mcp.client_headers import CLIENT_ID, USER_AGENT_PREFIX, client_header, client_request_headers, user_agent


def test_user_agent_format() -> None:
    ua = user_agent()
    assert ua.startswith(f"{USER_AGENT_PREFIX} ")
    assert len(ua.split()) >= 2


def test_client_header_format() -> None:
    header = client_header()
    assert header.startswith(f"{CLIENT_ID}/")


def test_client_request_headers() -> None:
    headers = client_request_headers()
    assert headers == {
        "User-Agent": user_agent(),
        "X-Cartesia-Client": client_header(),
    }
