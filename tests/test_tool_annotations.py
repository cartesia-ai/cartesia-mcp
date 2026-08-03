"""Anthropic Connectors Directory requires annotations.title and read/destructive hints."""

from __future__ import annotations

import asyncio

import cartesia_mcp.server as server


def test_all_tools_have_annotation_title_and_hint():
    tools = server.mcp._tool_manager.list_tools()
    assert len(tools) == 16

    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} is missing annotations"
        assert tool.annotations.title, f"{tool.name} is missing annotations.title"
        assert tool.annotations.read_only_hint is not None, (
            f"{tool.name} must set read_only_hint explicitly"
        )
        if tool.annotations.read_only_hint:
            assert tool.annotations.destructive_hint in (None, False), (
                f"{tool.name} is read-only but sets destructive_hint"
            )
        else:
            assert tool.annotations.destructive_hint is not None, (
                f"{tool.name} must set destructive_hint when read_only_hint is false"
            )


def test_read_only_tools():
    read_only = {
        "download_file",
        "get_voice",
        "list_voices",
        "speech_to_text",
        "get_credit_usage",
        "list_pronunciation_dicts",
        "get_pronunciation_dict",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in read_only:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint in (None, False)


def test_additive_tools():
    additive_tools = {
        "text_to_speech",
        "voice_change",
        "localize_voice",
        "clone_voice",
        "create_pronunciation_dict",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in additive_tools:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is False


def test_destructive_tools():
    destructive_tools = {
        "delete_voice",
        "update_voice",
        "update_pronunciation_dict",
        "delete_pronunciation_dict",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in destructive_tools:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is True


def test_wire_format_exposes_annotation_title():
    tools = asyncio.run(server.mcp.list_tools())
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.title


def test_text_to_speech_voice_id_has_string_type():
    tools = asyncio.run(server.mcp.list_tools())
    tts = next(tool for tool in tools if tool.name == "text_to_speech")
    voice_id = tts.input_schema["properties"]["voice_id"]
    assert voice_id["type"] == "string"
