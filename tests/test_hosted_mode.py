"""Tests for hosted mode configuration."""

from cartesia_mcp.hosted import hosted_enabled


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
