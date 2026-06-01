"""Unit tests for API key env parsing and validation."""

from __future__ import annotations

import pytest

from cartesia_mcp.config import (
    ADMIN_HTTP_REQUIRED_MESSAGE,
    ensure_admin_http,
    env_or_none,
    validate_api_keys,
)
from cartesia_mcp.sdk_setup import is_admin_api_key

STANDARD_KEY = "sk_car_testId1234567890ab.secretPartHere1234567890abcdefghij"
ADMIN_KEY = "sk_car_admin_testId1234567890ab.secretPartHere1234567890abcdefghij"


class TestEnvOrNone:
    def test_missing(self) -> None:
        assert env_or_none("CARTESIA_API_KEY", {}) is None

    def test_empty_string(self) -> None:
        assert env_or_none("CARTESIA_API_KEY", {"CARTESIA_API_KEY": ""}) is None

    def test_whitespace_only(self) -> None:
        assert env_or_none("CARTESIA_API_KEY", {"CARTESIA_API_KEY": "   "}) is None

    def test_strips_value(self) -> None:
        assert env_or_none("CARTESIA_API_KEY", {"CARTESIA_API_KEY": f"  {STANDARD_KEY}  "}) == STANDARD_KEY


class TestIsAdminApiKey:
    def test_admin_prefix(self) -> None:
        assert is_admin_api_key(ADMIN_KEY) is True

    def test_standard_prefix(self) -> None:
        assert is_admin_api_key(STANDARD_KEY) is False


class TestValidateApiKeys:
    def test_requires_standard_key(self) -> None:
        with pytest.raises(ValueError, match="CARTESIA_API_KEY is required"):
            validate_api_keys(None, None)

    def test_rejects_admin_key_as_standard(self) -> None:
        with pytest.raises(ValueError, match="not an admin key"):
            validate_api_keys(ADMIN_KEY, None)

    def test_rejects_non_admin_admin_key(self) -> None:
        with pytest.raises(ValueError, match="must be an admin API key"):
            validate_api_keys(STANDARD_KEY, STANDARD_KEY)

    def test_accepts_standard_only(self) -> None:
        api, admin = validate_api_keys(STANDARD_KEY, None)
        assert api == STANDARD_KEY
        assert admin is None

    def test_accepts_standard_and_admin(self) -> None:
        api, admin = validate_api_keys(STANDARD_KEY, ADMIN_KEY)
        assert api == STANDARD_KEY
        assert admin == ADMIN_KEY


class TestEnsureAdminHttp:
    def test_raises_when_unset(self) -> None:
        with pytest.raises(ValueError, match="CARTESIA_ADMIN_API_KEY"):
            ensure_admin_http(None)

    def test_returns_client(self) -> None:
        sentinel = object()
        assert ensure_admin_http(sentinel) is sentinel

    def test_message_documents_playground(self) -> None:
        assert "Keys → Admin" in ADMIN_HTTP_REQUIRED_MESSAGE
