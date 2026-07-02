"""Tests for hosted mode configuration."""

from cartesia_mcp.hosted import (
    fastmcp_hosted_kwargs,
    hosted_enabled,
    mcp_resource_url,
    server_public_url,
)


def test_hosted_enabled_parses_truthy_values(monkeypatch):
    monkeypatch.delenv("MCP_HOSTED", raising=False)
    assert hosted_enabled() is False

    for value in ("1", "true", "yes", "on", "TRUE"):
        monkeypatch.setenv("MCP_HOSTED", value)
        assert hosted_enabled() is True


def test_hosted_enabled_rejects_falsey_values(monkeypatch):
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("MCP_HOSTED", value)
        assert hosted_enabled() is False


def test_mcp_resource_url_appends_mcp_path(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "https://mcp.cartesia.ai")
    assert server_public_url() == "https://mcp.cartesia.ai"
    assert mcp_resource_url() == "https://mcp.cartesia.ai/mcp"


def test_fastmcp_hosted_auth_urls(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "https://mcp.cartesia.ai")
    kwargs = fastmcp_hosted_kwargs()
    assert str(kwargs["auth"].issuer_url).rstrip("/") == "https://mcp.cartesia.ai"
    assert str(kwargs["auth"].resource_server_url).rstrip("/") == "https://mcp.cartesia.ai/mcp"
    assert kwargs["streamable_http_path"] == "/mcp"
