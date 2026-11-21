"""Host client bind keys in the OAuth store (Redis in production)."""

from cartesia_mcp.mcp_host_client import (
    dogstatsd_mcp_client_tag,
    forget_session_host_client,
    remember_host_client,
    resolve_host_client,
)
from cartesia_mcp.mcp_http import McpClientInfo
from cartesia_mcp.oauth_store import MemoryBackend, oauth_store


def setup_function() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


def test_resolve_prefers_session_then_credential():
    session = McpClientInfo(name="cursor-vscode", version="1.0.0")
    cred = McpClientInfo(name="claude-code", version="2.0.0")
    remember_host_client(session, session_id="sess-a")
    remember_host_client(cred, credential_key="oauth-client:log-client")
    assert (
        resolve_host_client(
            session_id="sess-a",
            credential_key="oauth-client:log-client",
        )
        == session
    )
    assert resolve_host_client(credential_key="oauth-client:log-client") == cred
    forget_session_host_client("sess-a")
    assert (
        resolve_host_client(
            session_id="sess-a",
            credential_key="oauth-client:log-client",
        )
        == cred
    )


def test_dogstatsd_mcp_client_tag_sanitizes():
    assert dogstatsd_mcp_client_tag("cursor-vscode") == "cursor-vscode"
    assert dogstatsd_mcp_client_tag("Claude Code") == "Claude-Code"
    assert dogstatsd_mcp_client_tag(None) == "other"
    assert dogstatsd_mcp_client_tag("") == "other"
