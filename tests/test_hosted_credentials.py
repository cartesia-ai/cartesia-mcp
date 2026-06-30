"""Tests for hosted MCP credential resolution."""

import pytest

from cartesia_mcp.credentials import (
    configure_hosted_mode,
    configure_stdio_credentials,
    is_valid_bearer_credential,
    looks_like_cartesia_access_token,
    looks_like_cartesia_api_key,
    resolve_admin_api_credential,
    resolve_api_credential,
    set_hosted_admin_credential,
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


def test_hosted_admin_does_not_fall_back_to_stdio_env():
    configure_stdio_credentials("sk_car_test.key", "sk_car_admin_test.key")
    configure_hosted_mode()
    set_hosted_admin_credential(None)
    assert resolve_admin_api_credential() is None

    set_hosted_admin_credential("sk_car_admin_oauth.key")
    assert resolve_admin_api_credential() == "sk_car_admin_oauth.key"
    set_hosted_admin_credential(None)
    configure_hosted_mode(enabled=False)


def test_stdio_admin_still_uses_env():
    configure_hosted_mode(enabled=False)
    set_hosted_admin_credential(None)
    configure_stdio_credentials("sk_car_test.key", "sk_car_admin_test.key")
    assert resolve_admin_api_credential() == "sk_car_admin_test.key"
