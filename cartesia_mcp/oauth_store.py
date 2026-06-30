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
    connect_token: str
    cartesia_credential: str | None = None
    cartesia_admin_credential: str | None = None
    completing_owner_id: str | None = None
    completing_user_id: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class StoredMcpAccessToken:
    token: str
    cartesia_credential: str
    client_id: str
    scopes: list[str]
    expires_at: int
    cartesia_admin_credential: str | None = None


class OAuthStore:
    def __init__(self) -> None:
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._pending: dict[str, PendingConnectSession] = {}
        self._completed_redirects: dict[str, str] = {}
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
    ) -> tuple[str, str]:
        session_id = secrets.token_urlsafe(32)
        connect_token = secrets.token_urlsafe(32)
        self._pending[session_id] = PendingConnectSession(
            client_id=client_id,
            params=params,
            connect_token=connect_token,
        )
        return session_id, connect_token

    def get_pending_session(
        self,
        session_id: str,
        connect_token: str,
    ) -> PendingConnectSession:
        pending = self._pending.get(session_id)
        if pending is None or not secrets.compare_digest(
            pending.connect_token, connect_token
        ):
            raise KeyError(f"Unknown MCP OAuth session: {session_id}")
        return pending

    def attach_credential(
        self,
        session_id: str,
        connect_token: str,
        cartesia_credential: str,
        *,
        completing_owner_id: str,
        completing_user_id: str,
        cartesia_admin_credential: str | None = None,
    ) -> PendingConnectSession:
        pending = self.get_pending_session(session_id, connect_token)
        if pending.cartesia_credential is not None:
            if (
                pending.completing_owner_id == completing_owner_id
                and pending.completing_user_id == completing_user_id
                and pending.cartesia_credential == cartesia_credential
                and pending.cartesia_admin_credential == cartesia_admin_credential
            ):
                return pending
            raise ValueError("MCP OAuth session already completed")
        if (
            pending.completing_owner_id is not None
            and pending.completing_owner_id != completing_owner_id
        ):
            raise ValueError("MCP OAuth session bound to a different organization")
        pending.completing_owner_id = completing_owner_id
        pending.completing_user_id = completing_user_id
        pending.cartesia_credential = cartesia_credential
        pending.cartesia_admin_credential = cartesia_admin_credential
        return pending

    def remember_completed_redirect(
        self,
        session_id: str,
        connect_token: str,
        completing_owner_id: str,
        completing_user_id: str,
        redirect_url: str,
    ) -> None:
        key = self._completed_redirect_key(
            session_id,
            connect_token,
            completing_owner_id,
            completing_user_id,
        )
        self._completed_redirects[key] = redirect_url

    def get_completed_redirect(
        self,
        session_id: str,
        connect_token: str,
        completing_owner_id: str,
        completing_user_id: str,
    ) -> str | None:
        key = self._completed_redirect_key(
            session_id,
            connect_token,
            completing_owner_id,
            completing_user_id,
        )
        return self._completed_redirects.get(key)

    def _completed_redirect_key(
        self,
        session_id: str,
        connect_token: str,
        completing_owner_id: str,
        completing_user_id: str,
    ) -> str:
        return f"{session_id}:{connect_token}:{completing_owner_id}:{completing_user_id}"

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
        cartesia_admin_credential: str | None = None,
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
            cartesia_admin_credential=cartesia_admin_credential,
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
            cartesia_admin_credential=stored.cartesia_admin_credential,
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
