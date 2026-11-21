"""Bind MCP initialize clientInfo to sessions and credentials for later tool calls.

In-memory, per replica. Session entries clear on session terminate. Credential
entries are an LRU so API-key / stateless clients still attribute tools/call.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict

from cartesia_mcp.mcp_http import McpClientInfo

_MAX_CREDENTIAL_ENTRIES = 4096
_HOST_TAG = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HOST_TAG_CLEAN = re.compile(r"[^A-Za-z0-9._-]+")

_lock = threading.Lock()
_session_clients: dict[str, McpClientInfo] = {}
_credential_clients: OrderedDict[str, McpClientInfo] = OrderedDict()


def clear_host_clients() -> None:
    """Reset maps (tests)."""
    with _lock:
        _session_clients.clear()
        _credential_clients.clear()


def remember_host_client(
    info: McpClientInfo,
    *,
    session_id: str | None = None,
    credential_key: str | None = None,
) -> None:
    with _lock:
        if session_id:
            _session_clients[session_id] = info
        if credential_key:
            _credential_clients[credential_key] = info
            _credential_clients.move_to_end(credential_key)
            while len(_credential_clients) > _MAX_CREDENTIAL_ENTRIES:
                _credential_clients.popitem(last=False)


def forget_session_host_client(session_id: str) -> None:
    with _lock:
        _session_clients.pop(session_id, None)


def resolve_host_client(
    *,
    session_id: str | None = None,
    credential_key: str | None = None,
) -> McpClientInfo | None:
    with _lock:
        if session_id is not None:
            found = _session_clients.get(session_id)
            if found is not None:
                return found
        if credential_key is not None:
            found = _credential_clients.get(credential_key)
            if found is not None:
                _credential_clients.move_to_end(credential_key)
                return found
    return None


def dogstatsd_mcp_client_tag(name: str | None) -> str:
    """Coarse mcp_client tag for DogStatsD. Unknown / unsafe → other."""
    if not name:
        return "other"
    cleaned = _HOST_TAG_CLEAN.sub("-", name).strip("-._")[:64]
    if not cleaned or _HOST_TAG.fullmatch(cleaned) is None:
        return "other"
    return cleaned
