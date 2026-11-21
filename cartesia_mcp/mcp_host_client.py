"""Bind MCP initialize clientInfo for later tool calls.

Durable keys live in the hosted OAuth store (Redis in production, memory in
tests) so attribution survives restarts and multiple replicas.

- OAuth: keyed by DCR client_id (stable across access-token refresh)
- API keys: keyed by a hash of the bearer
- Session id: short-lived extra lookup for the current MCP session
"""

from __future__ import annotations

import re

from starlette.requests import Request

from cartesia_mcp.mcp_http import (
    McpClientInfo,
    bearer_token,
    mcp_credential_key,
)
from cartesia_mcp.oauth_store import oauth_store

_HOST_TAG = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HOST_TAG_CLEAN = re.compile(r"[^A-Za-z0-9._-]+")


def durable_host_client_key(request: Request) -> str | None:
    """Stable attribution key for this credential. None when unauthenticated."""
    token = bearer_token(request)
    if token is None:
        return None
    stored = oauth_store.resolve_mcp_access_token(token)
    if stored is not None:
        return f"oauth-client:{stored.client_id}"
    return mcp_credential_key(request)


def _session_key(session_id: str | None) -> str | None:
    if not session_id:
        return None
    return f"sess:{session_id}"


def remember_host_client(
    info: McpClientInfo,
    *,
    session_id: str | None = None,
    credential_key: str | None = None,
) -> None:
    session_key = _session_key(session_id)
    if session_key is not None:
        oauth_store.put_host_client(session_key, info.name, info.version)
    if credential_key:
        oauth_store.put_host_client(credential_key, info.name, info.version)


def forget_session_host_client(session_id: str) -> None:
    session_key = _session_key(session_id)
    if session_key is not None:
        oauth_store.delete_host_client(session_key)


def resolve_host_client(
    *,
    session_id: str | None = None,
    credential_key: str | None = None,
) -> McpClientInfo | None:
    # Session first: it is the client that just initialized this connection.
    # Credential covers a different replica or a later token on the same OAuth client.
    for key in (_session_key(session_id), credential_key):
        if key is None:
            continue
        found = oauth_store.get_host_client(key)
        if found is None:
            continue
        name, version = found
        return McpClientInfo(name=name, version=version)
    return None


def dogstatsd_mcp_client_tag(name: str | None) -> str:
    """Coarse mcp_client tag for DogStatsD. Unknown / unsafe → other."""
    if not name:
        return "other"
    cleaned = _HOST_TAG_CLEAN.sub("-", name).strip("-._")[:64]
    if not cleaned or _HOST_TAG.fullmatch(cleaned) is None:
        return "other"
    return cleaned
