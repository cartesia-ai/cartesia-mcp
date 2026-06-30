"""In-memory OAuth state for hosted MCP (single-process; replace with Redis for scale)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


@dataclass
class PendingConnectSession:
    client_id: str
    params: AuthorizationParams
    cartesia_credential: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class StoredMcpAccessToken:
    token: str
    cartesia_credential: str
    client_id: str
    scopes: list[str]
    expires_at: int


class OAuthStore:
    def __init__(self) -> None:
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._pending: dict[str, PendingConnectSession] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._mcp_tokens: dict[str, StoredMcpAccessToken] = {}

    def register_client(self, client: OAuthClientInformationFull) -> None:
        self._clients[client.client_id] = client

    def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    def create_pending_session(
        self,
        client_id: str,
        params: AuthorizationParams,
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        self._pending[session_id] = PendingConnectSession(
            client_id=client_id,
            params=params,
        )
        return session_id

    def attach_credential(self, session_id: str, cartesia_credential: str) -> PendingConnectSession:
        pending = self._pending.get(session_id)
        if pending is None:
            raise KeyError(f"Unknown MCP OAuth session: {session_id}")
        pending.cartesia_credential = cartesia_credential
        return pending

    def pop_pending(self, session_id: str) -> PendingConnectSession:
        pending = self._pending.pop(session_id, None)
        if pending is None:
            raise KeyError(f"Unknown MCP OAuth session: {session_id}")
        return pending

    def issue_authorization_code(
        self,
        *,
        client_id: str,
        params: AuthorizationParams,
        cartesia_credential: str,
    ) -> AuthorizationCode:
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            scopes=list(params.scopes or []),
            expires_at=time.time() + 600,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        self._auth_codes[code] = auth_code
        self._mcp_tokens[f"code:{code}"] = StoredMcpAccessToken(
            token=f"code:{code}",
            cartesia_credential=cartesia_credential,
            client_id=client_id,
            scopes=list(params.scopes or []),
            expires_at=int(time.time()) + 600,
        )
        return auth_code

    def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        stored = self._auth_codes.get(authorization_code)
        if stored is None or stored.client_id != client.client_id:
            return None
        if stored.expires_at < time.time():
            return None
        return stored

    def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        stored = self._mcp_tokens.pop(f"code:{authorization_code.code}", None)
        self._auth_codes.pop(authorization_code.code, None)
        if stored is None:
            raise ValueError("Authorization code not found")

        access_token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 3600
        self._mcp_tokens[access_token] = StoredMcpAccessToken(
            token=access_token,
            cartesia_credential=stored.cartesia_credential,
            client_id=client.client_id,
            scopes=stored.scopes,
            expires_at=expires_at,
        )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            scope=" ".join(stored.scopes) if stored.scopes else None,
        )

    def resolve_mcp_access_token(self, token: str) -> StoredMcpAccessToken | None:
        stored = self._mcp_tokens.get(token)
        if stored is None:
            return None
        if stored.expires_at < int(time.time()):
            return None
        return stored


oauth_store = OAuthStore()
