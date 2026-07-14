"""Tests for OAuth store authorization code exchange and refresh."""

from pydantic import AnyUrl
import pytest

from cartesia_mcp.oauth_provider import CartesiaOAuthProvider
from cartesia_mcp.oauth_store import (
    ACCESS_TOKEN_TTL_SECONDS,
    MemoryBackend,
    configure_oauth_store_from_env,
    oauth_store,
)
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull


def _reset_store() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="test-client",
        client_secret=None,
        redirect_uris=[AnyUrl("cursor://callback")],
        client_name="Test",
        token_endpoint_auth_method="none",
    )


def _params() -> AuthorizationParams:
    return AuthorizationParams(
        state="state123",
        scopes=["mcp"],
        code_challenge="challenge",
        redirect_uri=AnyUrl("cursor://callback"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


def test_oauth_code_exchange_roundtrip():
    _reset_store()

    client = _client()
    oauth_store.register_client(client)
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )
    pending = oauth_store.pop_pending(session_id)

    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    redirect = provider.build_resume_redirect(session_id, pending)
    assert "code=" in redirect
    assert "state=state123" in redirect

    auth_code_value = redirect.split("code=")[1].split("&")[0]
    auth_code = oauth_store.load_authorization_code(client, auth_code_value)
    assert auth_code is not None

    token = oauth_store.exchange_authorization_code(client, auth_code)
    assert token.access_token
    assert token.refresh_token
    assert token.expires_in == ACCESS_TOKEN_TTL_SECONDS

    loaded = oauth_store.resolve_mcp_access_token(token.access_token)
    assert loaded is not None
    assert loaded.cartesia_credential == "sk_car_oauth_test_key"
    assert loaded.cartesia_admin_credential is None


def test_oauth_admin_credential_propagates_to_access_token():
    _reset_store()

    client = _client()
    oauth_store.register_client(client)
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
        cartesia_admin_credential="sk_car_admin_test.key",
    )
    pending = oauth_store.pop_pending(session_id)

    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    redirect = provider.build_resume_redirect(session_id, pending)
    auth_code_value = redirect.split("code=")[1].split("&")[0]
    auth_code = oauth_store.load_authorization_code(client, auth_code_value)
    assert auth_code is not None

    token = oauth_store.exchange_authorization_code(client, auth_code)
    loaded = oauth_store.resolve_mcp_access_token(token.access_token)
    assert loaded is not None
    assert loaded.cartesia_admin_credential == "sk_car_admin_test.key"

    refresh = oauth_store.load_refresh_token(client, token.refresh_token or "")
    assert refresh is not None
    rotated = oauth_store.exchange_refresh_token(client, refresh, scopes=["mcp"])
    loaded_after = oauth_store.resolve_mcp_access_token(rotated.access_token)
    assert loaded_after is not None
    assert loaded_after.cartesia_admin_credential == "sk_car_admin_test.key"


def test_refresh_token_rotation_revokes_previous_tokens():
    _reset_store()
    client = _client()
    oauth_store.register_client(client)
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )
    pending = oauth_store.pop_pending(session_id)
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    redirect = provider.build_resume_redirect(session_id, pending)
    auth_code_value = redirect.split("code=")[1].split("&")[0]
    auth_code = oauth_store.load_authorization_code(client, auth_code_value)
    assert auth_code is not None
    first = oauth_store.exchange_authorization_code(client, auth_code)

    refresh = oauth_store.load_refresh_token(client, first.refresh_token or "")
    assert refresh is not None
    second = oauth_store.exchange_refresh_token(client, refresh, scopes=[])

    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert oauth_store.resolve_mcp_access_token(first.access_token) is None
    assert oauth_store.load_refresh_token(client, first.refresh_token or "") is None
    assert oauth_store.resolve_mcp_access_token(second.access_token) is not None


def test_connect_token_required():
    _reset_store()
    client = _client()
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )

    with pytest.raises(KeyError):
        oauth_store.attach_credential(
            session_id,
            "wrong-token",
            "sk_car_oauth_test_key",
            completing_owner_id="org_test",
            completing_user_id="user_test",
        )

    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )

    with pytest.raises(ValueError, match="already completed"):
        oauth_store.attach_credential(
            session_id,
            connect_token,
            "sk_car_other_test_key",
            completing_owner_id="org_test",
            completing_user_id="user_test",
        )


def test_attach_credential_is_idempotent_for_same_payload():
    _reset_store()
    client = _client()
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )

    first = oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
        cartesia_admin_credential="sk_car_admin_test.key",
    )
    second = oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
        cartesia_admin_credential="sk_car_admin_test.key",
    )
    assert second.cartesia_credential == first.cartesia_credential
    assert second.cartesia_admin_credential == first.cartesia_admin_credential
    assert second.completing_owner_id == first.completing_owner_id


def test_attach_credential_allows_admin_upgrade_on_retry():
    _reset_store()
    client = _client()
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )

    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )
    updated = oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
        cartesia_admin_credential="sk_car_admin_test.key",
    )
    assert updated.cartesia_admin_credential == "sk_car_admin_test.key"


def test_completed_session_retries_issue_fresh_code():
    _reset_store()
    client = _client()
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )
    pending = oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )
    oauth_store.remember_completed_session(
        session_id,
        connect_token,
        "org_test",
        "user_test",
        pending,
    )

    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    first = provider.build_resume_redirect(session_id, pending)
    second = provider.build_resume_redirect(
        session_id,
        oauth_store.get_completed_session(
            session_id,
            connect_token,
            "org_test",
            "user_test",
        ),
    )
    assert first != second
    assert "code=" in second


def test_configure_hosted_requires_redis_url():
    _reset_store()
    with pytest.raises(RuntimeError, match="REDIS_URL is required"):
        configure_oauth_store_from_env(hosted=True, redis_url=None)


def test_redis_backend_json_roundtrip(monkeypatch):
    """RedisBackend must survive JSON encode/decode of OAuth payloads."""
    from cartesia_mcp.oauth_store import RedisBackend, OAuthStore

    class _FakeRedis:
        def __init__(self) -> None:
            self._data: dict[str, str] = {}

        def ping(self) -> bool:
            return True

        def get(self, key: str) -> str | None:
            return self._data.get(key)

        def set(self, key: str, value: str) -> None:
            self._data[key] = value

        def setex(self, key: str, ttl: int, value: str) -> None:
            self._data[key] = value

        def delete(self, key: str) -> None:
            self._data.pop(key, None)

    fake = _FakeRedis()

    class _FakeRedisModule:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return fake

    monkeypatch.setitem(__import__("sys").modules, "redis", _FakeRedisModule)

    store = OAuthStore(RedisBackend("redis://localhost:6379/0"))
    client = _client()
    store.register_client(client)
    loaded_client = store.get_client(client.client_id)
    assert loaded_client is not None
    assert loaded_client.client_id == client.client_id

    session_id, connect_token = store.create_pending_session(
        client.client_id,
        _params(),
    )
    store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
        cartesia_admin_credential="sk_car_admin_test.key",
    )
    pending = store.pop_pending(session_id)
    auth_code = store.issue_authorization_code(
        client_id=pending.client_id,
        params=pending.params,
        cartesia_credential=pending.cartesia_credential or "",
        cartesia_admin_credential=pending.cartesia_admin_credential,
    )
    loaded_code = store.load_authorization_code(client, auth_code.code)
    assert loaded_code is not None
    token = store.exchange_authorization_code(client, loaded_code)
    assert token.refresh_token
    resolved = store.resolve_mcp_access_token(token.access_token)
    assert resolved is not None
    assert resolved.cartesia_credential == "sk_car_oauth_test_key"
    assert resolved.cartesia_admin_credential == "sk_car_admin_test.key"


def test_revoke_token_removes_access_and_refresh():
    _reset_store()
    client = _client()
    oauth_store.register_client(client)
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )
    pending = oauth_store.pop_pending(session_id)
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    redirect = provider.build_resume_redirect(session_id, pending)
    auth_code = oauth_store.load_authorization_code(
        client,
        redirect.split("code=")[1].split("&")[0],
    )
    assert auth_code is not None
    token = oauth_store.exchange_authorization_code(client, auth_code)
    oauth_store.revoke_token(token.access_token)
    assert oauth_store.resolve_mcp_access_token(token.access_token) is None
    assert oauth_store.load_refresh_token(client, token.refresh_token or "") is None
