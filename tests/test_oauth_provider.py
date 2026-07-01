"""Tests for OAuth provider token loading."""

import asyncio

from cartesia_mcp.oauth_provider import CartesiaOAuthProvider
from cartesia_mcp.oauth_store import StoredMcpAccessToken, oauth_store


def test_mcp_oauth_access_token_resolves_stored_credential():
    oauth_store._mcp_tokens.clear()
    mcp_token = "mcp_oauth_access_token_example"
    oauth_store._mcp_tokens[mcp_token] = StoredMcpAccessToken(
        token=mcp_token,
        cartesia_credential="sk_car_oauth_test_key",
        client_id="test-client",
        scopes=["mcp"],
        expires_at=9999999999,
        cartesia_admin_credential="sk_car_admin_test.key",
    )

    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    access = asyncio.run(provider.load_access_token(mcp_token))

    assert access is not None
    assert access.token == "sk_car_oauth_test_key"
    assert access.client_id == "test-client"
