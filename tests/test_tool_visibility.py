"""Tests for admin-only tool visibility in MCP tool listings."""

from __future__ import annotations

import asyncio

import cartesia_mcp.server as server
from cartesia_mcp.tool_visibility import (
    ADMIN_ONLY_TOOLS,
    admin_tools_available,
    is_tool_visible,
)


def test_admin_only_tools_constant():
    assert ADMIN_ONLY_TOOLS == frozenset({"get_credit_usage"})


def test_is_tool_visible_hides_admin_tools_without_credential(monkeypatch):
    monkeypatch.setattr(
        "cartesia_mcp.tool_visibility.resolve_admin_api_credential",
        lambda: None,
    )
    assert admin_tools_available() is False
    assert is_tool_visible("list_voices") is True
    assert is_tool_visible("get_credit_usage") is False


def test_is_tool_visible_shows_admin_tools_with_credential(monkeypatch):
    monkeypatch.setattr(
        "cartesia_mcp.tool_visibility.resolve_admin_api_credential",
        lambda: "sk_car_admin_test.key",
    )
    assert admin_tools_available() is True
    assert is_tool_visible("get_credit_usage") is True


def test_list_tools_hides_admin_tools_without_credential(monkeypatch):
    monkeypatch.setattr(
        "cartesia_mcp.tool_visibility.resolve_admin_api_credential",
        lambda: None,
    )
    tools = asyncio.run(server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert len(names) == 17
    assert "get_credit_usage" not in names


def test_list_tools_shows_admin_tools_with_credential(monkeypatch):
    monkeypatch.setattr(
        "cartesia_mcp.tool_visibility.resolve_admin_api_credential",
        lambda: "sk_car_admin_test.key",
    )
    tools = asyncio.run(server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert len(names) == 18
    assert "get_credit_usage" in names
