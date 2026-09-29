"""README stays aligned with the hosted session-creation limits."""

from __future__ import annotations

from pathlib import Path

from cartesia_mcp.mcp_rate_limit import (
    MCP_INITIALIZE_IP_RATE_LIMIT,
    MCP_INITIALIZE_RATE_LIMIT,
    MCP_INITIALIZE_RATE_WINDOW_SECONDS,
)
from cartesia_mcp.mcp_session_guard import MCP_SESSION_IDLE_TIMEOUT_SECONDS

_README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_documents_session_creation_limits() -> None:
    readme = _README.read_text()
    section = readme.split("### Hosted sessions and rate limits", 1)[1].split("### ", 1)[0]
    assert "mcp-session-id" in section
    assert "Retry-After" in section
    assert "not an expired login" in section
    assert f"**{MCP_INITIALIZE_RATE_LIMIT} per minute per access token**" in section
    assert f"**{MCP_INITIALIZE_IP_RATE_LIMIT} per minute per client IP**" in section
    assert str(MCP_INITIALIZE_RATE_WINDOW_SECONDS) in section
    idle_minutes = MCP_SESSION_IDLE_TIMEOUT_SECONDS // 60
    assert f"{idle_minutes} minutes" in section
