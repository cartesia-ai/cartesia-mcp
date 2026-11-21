"""Host client bind maps for session + credential attribution."""

from cartesia_mcp.mcp_host_client import (
    clear_host_clients,
    dogstatsd_mcp_client_tag,
    forget_session_host_client,
    remember_host_client,
    resolve_host_client,
)
from cartesia_mcp.mcp_http import McpClientInfo


def setup_function() -> None:
    clear_host_clients()


def test_resolve_prefers_session_then_credential():
    session = McpClientInfo(name="cursor-vscode", version="1.0.0")
    cred = McpClientInfo(name="claude-code", version="2.0.0")
    remember_host_client(session, session_id="sess-a")
    remember_host_client(cred, credential_key="tok:abc")
    assert resolve_host_client(session_id="sess-a", credential_key="tok:abc") == session
    assert resolve_host_client(credential_key="tok:abc") == cred
    forget_session_host_client("sess-a")
    assert resolve_host_client(session_id="sess-a", credential_key="tok:abc") == cred


def test_dogstatsd_mcp_client_tag_sanitizes():
    assert dogstatsd_mcp_client_tag("cursor-vscode") == "cursor-vscode"
    assert dogstatsd_mcp_client_tag("Claude Code") == "Claude-Code"
    assert dogstatsd_mcp_client_tag(None) == "other"
    assert dogstatsd_mcp_client_tag("") == "other"
