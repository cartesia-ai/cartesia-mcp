"""Tests for OAuth provider token loading and refresh."""

import asyncio

import pytest
from cartesia_mcp.oauth_provider import (
    CartesiaOAuthProvider,
    _redirect_uri_is_allowed,
)
from cartesia_mcp.oauth_store import MemoryBackend, oauth_store
from mcp.server.auth.provider import AuthorizationParams, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


def _reset_store() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


@pytest.mark.parametrize(
    ("uri", "allowed"),
    [
        ("cursor://anysphere.cursor-mcp/oauth/callback", True),
        ("vscode://vscode.github-authentication/oauth/callback", True),
        ("vscode-insiders://callback", True),
        ("http://127.0.0.1:58135/callback", True),
        ("http://localhost:3118/callback", True),
        ("http://[::1]:8080/callback", True),
        ("https://claude.ai/api/mcp/auth_callback", True),
        ("https://chatgpt.com/connector_platform_oauth_redirect", True),
        ("https://chatgpt.com/connector/oauth/abc123", True),
        ("https://evil.attacker.com/steal", False),
        ("https://example.com/callback", False),
        ("https://claude.ai/evil", False),
        ("https://chatgpt.com/other", False),
        ("javascript:alert(1)", False),
        ("data:text/html,hi", False),
        ("http://evil.com/callback", False),
        ("https://user:pass@claude.ai/api/mcp/auth_callback", False),
        ("cursor:", False),
    ],
)
def test_redirect_uri_allowlist(uri: str, allowed: bool):
    assert _redirect_uri_is_allowed(uri) is allowed


def test_register_client_rejects_arbitrary_https_redirect():
    _reset_store()
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    client = OAuthClientInformationFull(
        client_id="evil-client",
        client_secret=None,
        redirect_uris=[AnyUrl("https://evil.attacker.com/steal")],
        client_name="Evil",
        token_endpoint_auth_method="none",
    )
    with pytest.raises(RegistrationError):
        asyncio.run(provider.register_client(client))


def test_build_resume_redirect_rejects_disallowed_uri():
    _reset_store()
    client = _client()
    # Simulate a client registered before the allowlist existed.
    client.redirect_uris = [AnyUrl("https://evil.attacker.com/steal")]
    oauth_store.register_client(client)
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        AuthorizationParams(
            state="s",
            scopes=["mcp"],
            code_challenge="challenge",
            redirect_uri=AnyUrl("https://evil.attacker.com/steal"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_test",
        completing_user_id="user_test",
    )
    pending = oauth_store.pop_pending(session_id)
    with pytest.raises(ValueError, match="redirect_uri is not allowed"):
        provider.build_resume_redirect(session_id, pending)



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
        state="s",
        scopes=["mcp"],
        code_challenge="challenge",
        redirect_uri=AnyUrl("cursor://callback"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


def _issue_tokens(provider: CartesiaOAuthProvider, client: OAuthClientInformationFull):
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
    redirect = provider.build_resume_redirect(session_id, pending)
    auth_code = asyncio.run(
        provider.load_authorization_code(
            client,
            redirect.split("code=")[1].split("&")[0],
        )
    )
    assert auth_code is not None
    return asyncio.run(provider.exchange_authorization_code(client, auth_code))


def test_mcp_oauth_access_token_resolves_stored_credential():
    _reset_store()
    client = _client()
    oauth_store.register_client(client)
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    token = _issue_tokens(provider, client)
    access = asyncio.run(provider.load_access_token(token.access_token))

    assert access is not None
    assert access.token == "sk_car_oauth_test_key"
    assert access.client_id == "test-client"


def test_provider_refresh_grant_rotates_tokens():
    _reset_store()
    client = _client()
    oauth_store.register_client(client)
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    first = _issue_tokens(provider, client)
    assert first.refresh_token

    refresh = asyncio.run(provider.load_refresh_token(client, first.refresh_token))
    assert refresh is not None
    second = asyncio.run(
        provider.exchange_refresh_token(client, refresh, scopes=["mcp"])
    )
    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token

    access = asyncio.run(provider.load_access_token(second.access_token))
    assert access is not None
    assert access.token == "sk_car_oauth_test_key"


def test_provider_revoke_uses_opaque_mcp_bearer():
    _reset_store()
    client = _client()
    oauth_store.register_client(client)
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    issued = _issue_tokens(provider, client)
    access = asyncio.run(provider.load_access_token(issued.access_token))
    assert access is not None
    assert access.token == "sk_car_oauth_test_key"
    assert (access.claims or {}).get("mcp_access_token") == issued.access_token

    asyncio.run(provider.revoke_token(access))
    assert oauth_store.resolve_mcp_access_token(issued.access_token) is None
    assert oauth_store.load_refresh_token(client, issued.refresh_token or "") is None
