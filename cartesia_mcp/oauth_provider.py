"""MCP OAuth authorization server backed by Clerk login on the playground."""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from cartesia_mcp.oauth_store import PendingConnectSession, oauth_store

# Schemes that must never be treated as "native app" redirects.
_BLOCKED_REDIRECT_SCHEMES = frozenset(
    {
        "http",
        "https",
        "javascript",
        "data",
        "file",
        "blob",
        "vbscript",
        "about",
    }
)

# RFC 8252 loopback hosts (port may be ephemeral).
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# First-party HTTPS OAuth callbacks for known MCP hosts. Path must match exactly
# unless listed with a trailing "/" as a prefix.
#
# Desktop clients usually use loopback http or a custom scheme (allowed below).
# Hosted web clients need an explicit HTTPS entry here (or via
# MCP_OAUTH_EXTRA_HTTPS_REDIRECTS) — do not open arbitrary https:// hosts.
_HTTPS_REDIRECT_EXACT = frozenset(
    {
        ("claude.ai", "/api/mcp/auth_callback"),
        ("claude.com", "/api/mcp/auth_callback"),
        ("chatgpt.com", "/connector_platform_oauth_redirect"),
        ("www.cursor.com", "/agents/mcp/oauth/callback"),
        ("cursor.com", "/agents/mcp/oauth/callback"),
        ("vscode.dev", "/redirect"),
        ("insiders.vscode.dev", "/redirect"),
    }
)
_HTTPS_REDIRECT_PREFIXES = (
    ("chatgpt.com", "/connector/oauth/"),
)


def _extra_https_redirects_from_env() -> frozenset[tuple[str, str]]:
    """Optional exact (host, path) pairs from MCP_OAUTH_EXTRA_HTTPS_REDIRECTS.

    Format: comma-separated ``host|path`` entries, e.g.
    ``example.com|/oauth/callback,www.example.com|/oauth/callback``.
    """
    raw = os.environ.get("MCP_OAUTH_EXTRA_HTTPS_REDIRECTS", "").strip()
    if not raw:
        return frozenset()
    pairs: set[tuple[str, str]] = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or "|" not in entry:
            continue
        host, path = entry.split("|", 1)
        host = host.strip().lower()
        path = path.strip()
        if host and path.startswith("/"):
            pairs.add((host, path))
    return frozenset(pairs)


def _redirect_uri_is_allowed(redirect_uri: AnyUrl | str) -> bool:
    """Return True when a DCR / authorize redirect_uri is safe to use.

    Open DCR is required for MCP clients, so the redirect URI is the security
    boundary: reject arbitrary https hosts that would receive auth codes.

    Allowed:
    - Custom URI schemes (desktop IDEs), except blocked web/script schemes
    - Loopback http (RFC 8252)
    - Allowlisted first-party https callbacks (+ env extras)
    """
    raw = (
        redirect_uri.unicode_string()
        if isinstance(redirect_uri, AnyUrl)
        else str(redirect_uri)
    )
    parsed = urlparse(raw)
    if parsed.username is not None or parsed.password is not None:
        return False

    scheme = parsed.scheme.lower()
    if scheme and scheme not in _BLOCKED_REDIRECT_SCHEMES:
        # Native / private-use schemes (cursor://, windsurf://, …).
        # Require a non-empty authority or path (reject bare "cursor:").
        return bool(parsed.netloc or parsed.path)

    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if scheme == "http":
        return host in _LOOPBACK_HOSTS

    if scheme == "https":
        exact = _HTTPS_REDIRECT_EXACT | _extra_https_redirects_from_env()
        if (host, path) in exact:
            return True
        return any(
            host == allowed_host and path.startswith(prefix)
            for allowed_host, prefix in _HTTPS_REDIRECT_PREFIXES
        )

    return False


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
                error_description=(
                    "redirect_uris must be a native app URI scheme, "
                    "loopback http, or an allowlisted https callback"
                ),
            )
        oauth_store.register_client(client_info)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if not _redirect_uri_is_allowed(params.redirect_uri):
            raise AuthorizeError(
                error="invalid_request",
                error_description="redirect_uri is not allowed",
            )
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
        if not _redirect_uri_is_allowed(pending.params.redirect_uri):
            # Block completions for clients registered before allowlisting.
            raise ValueError("redirect_uri is not allowed")
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
    if not _redirect_uri_is_allowed(redirect_uri):
        raise ValueError("redirect_uri is not allowed")
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
    if not all(_redirect_uri_is_allowed(uri) for uri in redirect_uris):
        raise ValueError("redirect_uri is not allowed")
    client = OAuthClientInformationFull(
        client_id=client_id,
        client_secret=None,
        redirect_uris=redirect_uris,
        client_name="MCP Client",
        token_endpoint_auth_method="none",
    )
    oauth_store.register_client(client)
    return client
