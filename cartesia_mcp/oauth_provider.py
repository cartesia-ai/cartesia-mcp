"""MCP OAuth authorization server backed by Clerk login on the playground."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from cartesia_mcp.oauth_store import PendingConnectSession, oauth_store

_ALLOWED_REDIRECT_SCHEMES = ("cursor:", "vscode:", "http:", "https:")


def _redirect_uri_is_allowed(redirect_uri: AnyUrl) -> bool:
    parsed = redirect_uri.unicode_string()
    return parsed.startswith(_ALLOWED_REDIRECT_SCHEMES)


class CartesiaOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
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
        if not all(_redirect_uri_is_allowed(uri) for uri in client_info.redirect_uris):
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="redirect_uris must use cursor, vscode, http, or https",
            )
        oauth_store.register_client(client_info)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        session_id, connect_token = oauth_store.create_pending_session(
            client.client_id,
            params,
        )
        query = urlencode({"session": session_id, "token": connect_token})
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
    ) -> RefreshToken | None:
        return oauth_store.load_refresh_token(client, refresh_token)

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        try:
            return oauth_store.exchange_refresh_token(client, refresh_token, scopes)
        except ValueError as exc:
            raise TokenError(error="invalid_grant", error_description=str(exc)) from exc

    async def load_access_token(self, token: str) -> AccessToken | None:
        stored = oauth_store.resolve_mcp_access_token(token)
        if stored is not None:
            from cartesia_mcp.credentials import set_hosted_admin_credential

            set_hosted_admin_credential(stored.cartesia_admin_credential)

            return AccessToken(
                # Tools resolve Cartesia credentials from AccessToken.token.
                token=stored.cartesia_credential,
                client_id=stored.client_id,
                scopes=stored.scopes or ["mcp"],
                expires_at=stored.expires_at,
                # Opaque MCP bearer (Redis key); used by revoke_token.
                claims={"mcp_access_token": token},
            )

        from cartesia_mcp.credentials import is_valid_bearer_credential

        if is_valid_bearer_credential(token):
            return AccessToken(
                token=token,
                client_id="cartesia_credential",
                scopes=["mcp"],
                expires_at=None,
            )

        return None

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        if isinstance(token, AccessToken):
            mcp_bearer = (token.claims or {}).get("mcp_access_token")
            if isinstance(mcp_bearer, str) and mcp_bearer:
                oauth_store.revoke_token(mcp_bearer)
            return
        oauth_store.revoke_token(token.token)

    def build_resume_redirect(
        self,
        session_id: str,
        pending: PendingConnectSession,
    ) -> str:
        auth_code = oauth_store.issue_authorization_code(
            client_id=pending.client_id,
            params=pending.params,
            cartesia_credential=pending.cartesia_credential or "",
            cartesia_admin_credential=pending.cartesia_admin_credential,
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
    redirect_uris = (
        [AnyUrl(redirect_uri)]
        if redirect_uri
        else [AnyUrl("cursor://anysphere.cursor-mcp/oauth/callback")]
    )
    client = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=None,
        redirect_uris=redirect_uris,
        client_name="MCP Client",
        token_endpoint_auth_method="none",
    )
    oauth_store.register_client(client)
    return client
