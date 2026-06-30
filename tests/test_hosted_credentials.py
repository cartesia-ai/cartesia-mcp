"""Tests for hosted MCP credential resolution."""

import pytest

from cartesia_mcp.credentials import (
    configure_stdio_credentials,
    is_valid_bearer_credential,
    looks_like_cartesia_access_token,
    looks_like_cartesia_api_key,
    resolve_api_credential,
)


def test_api_key_detection():
    assert looks_like_cartesia_api_key("sk_car_abc.def")
    assert not looks_like_cartesia_api_key("sk_car_admin_abc.def")


def test_access_token_detection():
    assert looks_like_cartesia_access_token("eyJhbGciOiJIUzI1NiJ9.payload.sig")


def test_valid_bearer_credential():
    assert is_valid_bearer_credential("sk_car_abc.def")
    assert is_valid_bearer_credential("eyJhbGciOiJIUzI1NiJ9.x.y")
    assert not is_valid_bearer_credential("sk_car_admin_abc.def")


def test_stdio_credential_resolution():
    configure_stdio_credentials("sk_car_test.key", None)
    assert resolve_api_credential() == "sk_car_test.key"


def test_missing_credential_raises():
    configure_stdio_credentials("sk_car_test.key", None)
    configure_stdio_credentials("", None)
    with pytest.raises(ValueError, match="No Cartesia credential"):
        resolve_api_credential()
    configure_stdio_credentials("sk_car_test.key", None)
