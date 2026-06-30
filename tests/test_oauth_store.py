"""Tests for OAuth store authorization code exchange."""

from pydantic import AnyUrl
import pytest

from cartesia_mcp.oauth_provider import CartesiaOAuthProvider
from cartesia_mcp.oauth_store import oauth_store
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull


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
    oauth_store._clients.clear()
    oauth_store._pending.clear()
    oauth_store._auth_codes.clear()
    oauth_store._mcp_tokens.clear()

    client = _client()
    oauth_store.register_client(client)
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "eyJcartesia.token",
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

    loaded = oauth_store.resolve_mcp_access_token(token.access_token)
    assert loaded is not None
    assert loaded.cartesia_credential == "eyJcartesia.token"


def test_oauth_admin_credential_propagates_to_access_token():
    oauth_store._clients.clear()
    oauth_store._pending.clear()
    oauth_store._auth_codes.clear()
    oauth_store._mcp_tokens.clear()

    client = _client()
    oauth_store.register_client(client)
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "eyJcartesia.token",
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


def test_connect_token_required():
    oauth_store._pending.clear()
    client = _client()
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )

    with pytest.raises(KeyError):
        oauth_store.attach_credential(
            session_id,
            "wrong-token",
            "eyJcartesia.token",
            completing_owner_id="org_test",
            completing_user_id="user_test",
        )

    oauth_store.attach_credential(
        session_id,
        connect_token,
        "eyJcartesia.token",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )

    with pytest.raises(ValueError, match="already completed"):
        oauth_store.attach_credential(
            session_id,
            connect_token,
            "eyJother.token",
            completing_owner_id="org_test",
            completing_user_id="user_test",
        )


def test_attach_credential_is_idempotent_for_same_payload():
    oauth_store._pending.clear()
    client = _client()
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        _params(),
    )

    first = oauth_store.attach_credential(
        session_id,
        connect_token,
        "eyJcartesia.token",
        completing_owner_id="org_test",
        completing_user_id="user_test",
        cartesia_admin_credential="sk_car_admin_test.key",
    )
    second = oauth_store.attach_credential(
        session_id,
        connect_token,
        "eyJcartesia.token",
        completing_owner_id="org_test",
        completing_user_id="user_test",
        cartesia_admin_credential="sk_car_admin_test.key",
    )
    assert second is first


def test_completed_redirect_is_reused():
    oauth_store._completed_redirects.clear()
    oauth_store.remember_completed_redirect(
        "session123",
        "token456",
        "org_test",
        "user_test",
        "cursor://callback?code=abc&state=xyz",
    )
    assert (
        oauth_store.get_completed_redirect(
            "session123",
            "token456",
            "org_test",
            "user_test",
        )
        == "cursor://callback?code=abc&state=xyz"
    )
    assert (
        oauth_store.get_completed_redirect(
            "session123",
            "wrong-token",
            "org_test",
            "user_test",
        )
        is None
    )
