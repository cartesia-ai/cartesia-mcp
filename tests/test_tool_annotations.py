"""Anthropic Connectors Directory requires title and read/destructive hints on every tool."""

from __future__ import annotations

import cartesia_mcp.server as server


def test_all_tools_have_title_and_hint():
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) == 20

    for tool in tools:
        assert tool.title, f"{tool.name} is missing title"
        assert tool.annotations is not None, f"{tool.name} is missing annotations"
        assert (
            tool.annotations.readOnlyHint or tool.annotations.destructiveHint
        ), f"{tool.name} must set readOnlyHint or destructiveHint"


def test_read_only_tools():
    read_only = {
        "download_file",
        "get_file",
        "get_voice",
        "list_files",
        "list_voices",
        "speech_to_text",
        "get_credit_usage",
        "list_pronunciation_dicts",
        "get_pronunciation_dict",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in read_only:
        assert tools[name].annotations is not None
        assert tools[name].annotations.readOnlyHint is True


def test_write_tools():
    write_tools = {
        "text_to_speech",
        "voice_change",
        "localize_voice",
        "delete_voice",
        "update_voice",
        "clone_voice",
        "create_pronunciation_dict",
        "update_pronunciation_dict",
        "delete_pronunciation_dict",
        "upload_file",
        "delete_file",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in write_tools:
        assert tools[name].annotations is not None
        assert tools[name].annotations.destructiveHint is True
