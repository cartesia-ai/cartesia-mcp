"""Advertised input constraints reject invalid calls before reaching the API."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

import cartesia_mcp.server as server


@pytest.mark.parametrize(
    ("tool_name", "parameter"),
    [
        ("text_to_speech", "voice_id"),
        ("localize_voice", "voice_id"),
        ("delete_voice", "voice_id"),
        ("get_voice", "voice_id"),
        ("update_voice", "voice_id"),
        ("add_voice_accents", "voice_id"),
        ("delete_voice_accent", "voice_id"),
        ("download_file", "file_id"),
        ("get_pronunciation_dict", "dict_id"),
        ("update_pronunciation_dict", "dict_id"),
        ("delete_pronunciation_dict", "dict_id"),
    ],
)
def test_required_resource_ids_advertise_minimum_length(tool_name, parameter):
    tools = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    assert tools[tool_name].input_schema["properties"][parameter]["minLength"] == 1


@pytest.mark.parametrize(
    ("tool_name", "arguments", "error"),
    [
        ("get_voice", {"voice_id": ""}, "voice_id"),
        ("download_file", {"file_id": ""}, "file_id"),
        ("delete_pronunciation_dict", {"dict_id": ""}, "dict_id"),
        ("list_voices", {"limit": 0}, "limit"),
        ("list_voices", {"limit": 101}, "limit"),
        ("list_pronunciation_dicts", {"limit": 0}, "limit"),
        ("list_pronunciation_dicts", {"limit": 101}, "limit"),
    ],
)
def test_invalid_inputs_do_not_reach_api(api, tool_name, arguments, error):
    with pytest.raises(ToolError, match=error):
        asyncio.run(server.mcp.call_tool(tool_name, arguments))
    assert api.requests == []


@pytest.mark.parametrize(
    ("tool_name", "path"),
    [("list_voices", "/voices"), ("list_pronunciation_dicts", "/pronunciation-dicts/")],
)
@pytest.mark.parametrize("limit", [1, 100])
def test_pagination_accepts_boundary_limits(api, tool_name, path, limit):
    api.on("GET", path, {"data": [], "has_more": False})
    result = asyncio.run(server.mcp.call_tool(tool_name, {"limit": limit}))
    assert isinstance(result, CallToolResult)
    assert not result.is_error
    assert api.last.url.params["limit"] == str(limit)
