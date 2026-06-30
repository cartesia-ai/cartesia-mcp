"""MCP OAuth authorization server backed by Clerk login on the playground."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from cartesia_mcp.oauth_store import oauth_store


class CartesiaOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, Any, AuthorizationCode]
):
    def __init__(self, *, playground_url: str, mcp_server_url: str) -> None:
        self._playground_url = playground_url.rstrip("/")
        self._mcp_server_url = mcp_server_url.rstrip("/")

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return oauth_store.get_client(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.redirect_uris:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="redirect_uris is required",
            )
        oauth_store.register_client(client_info)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        session_id = oauth_store.create_pending_session(client.client_id, params)
        query = urlencode({"session": session_id})
        return f"{self._playground_url}/mcp/connect?{query}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        return oauth_store.load_authorization_code(client, authorization_code)

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        try:
            return oauth_store.exchange_authorization_code(client, authorization_code)
        except ValueError as exc:
            raise TokenError(error="invalid_grant", error_description=str(exc)) from exc

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: Any,
        scopes: list[str],
    ) -> OAuthToken:
        raise TokenError(
            error="unsupported_grant_type",
            error_description="Refresh tokens are not supported",
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        from cartesia_mcp.credentials import is_valid_bearer_credential

        if is_valid_bearer_credential(token):
            return AccessToken(
                token=token,
                client_id="cartesia_credential",
                scopes=["mcp"],
                expires_at=None,
            )

        stored = oauth_store.resolve_mcp_access_token(token)
        if stored is None:
            return None

        return AccessToken(
            token=stored.cartesia_credential,
            client_id=stored.client_id,
            scopes=stored.scopes or ["mcp"],
            expires_at=stored.expires_at,
        )

    async def revoke_token(
        self,
        token: Any,
    ) -> None:
        if isinstance(token, str):
            oauth_store._mcp_tokens.pop(token, None)

    def build_resume_redirect(self, session_id: str, pending) -> str:
        auth_code = oauth_store.issue_authorization_code(
            client_id=pending.client_id,
            params=pending.params,
            cartesia_credential=pending.cartesia_credential or "",
        )
        query = urlencode(
            {
                "code": auth_code.code,
                "state": pending.params.state or "",
            }
        )
        redirect_base = str(pending.params.redirect_uri)
        separator = "&" if "?" in redirect_base else "?"
        return f"{redirect_base}{separator}{query}"


def ensure_dynamic_client(client_id: str, redirect_uri: AnyUrl) -> OAuthClientInformationFull:
    existing = oauth_store.get_client(client_id)
    if existing is not None:
        return existing
    client = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=None,
        redirect_uris=[redirect_uri],
        client_name="MCP Client",
        token_endpoint_auth_method="none",
    )
    oauth_store.register_client(client)
    return client


def register_ephemeral_client(redirect_uri: str | None = None) -> OAuthClientInformationFull:
    client_id = secrets.token_urlsafe(16)
    redirect_uris = [AnyUrl(redirect_uri)] if redirect_uri else [AnyUrl("cursor://anysphere.cursor-mcp/oauth/callback")]
    client = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=None,
        redirect_uris=redirect_uris,
        client_name="MCP Client",
        token_endpoint_auth_method="none",
    )
    oauth_store.register_client(client)
    return client
