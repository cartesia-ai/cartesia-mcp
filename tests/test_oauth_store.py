"""Tests for OAuth store authorization code exchange."""

from pydantic import AnyUrl

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


def test_oauth_code_exchange_roundtrip():
    oauth_store._clients.clear()
    oauth_store._pending.clear()
    oauth_store._auth_codes.clear()
    oauth_store._mcp_tokens.clear()

    client = _client()
    oauth_store.register_client(client)
    params = AuthorizationParams(
        state="state123",
        scopes=["mcp"],
        code_challenge="challenge",
        redirect_uri=AnyUrl("cursor://callback"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    session_id = oauth_store.create_pending_session(client.client_id, params)
    oauth_store.attach_credential(session_id, "eyJcartesia.token")
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
