"""Regression: list_voices last-page structured output must accept null next_page."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import jsonschema
from cartesia.types import Voice

import cartesia_mcp.server as server


def _list_voices_tool():
    return next(t for t in server.mcp._tool_manager.list_tools() if t.name == "list_voices")


def _list_voices_output_schema() -> dict:
    tools = asyncio.run(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "list_voices")
    assert tool.outputSchema is not None
    return tool.outputSchema


def _structured_content_for(result: dict) -> dict:
    """Mirror FastMCP FuncMetadata.convert_result structured dump path."""
    tool = _list_voices_tool()
    assert tool.fn_metadata.output_model is not None
    validated = tool.fn_metadata.output_model.model_validate(result)
    return validated.model_dump(mode="json", by_alias=True)


def _voice(**overrides: object) -> Voice:
    values = {
        "id": "voice_abc",
        "created_at": datetime.now(timezone.utc),
        "description": "internal clone",
        "is_owner": True,
        "is_public": False,
        "language": "en",
        "name": "internal_texas_clone",
        "country": None,
        "gender": None,
        "preview_file_url": None,
    }
    values.update(overrides)
    return Voice(**values)  # type: ignore[arg-type]


def test_list_voices_output_schema_allows_null_next_page() -> None:
    schema = _list_voices_output_schema()
    next_page_schema = schema["properties"]["next_page"]
    assert {"type": "null"} in next_page_schema.get("anyOf", [])


@patch("cartesia_mcp.server.client")
def test_list_voices_last_page_structured_output_validates(mock_client: MagicMock) -> None:
    """Final pages omit next_page; FastMCP dump fills it as null."""
    schema = _list_voices_output_schema()
    page = MagicMock()
    page.data = [_voice()]
    page.has_next_page = lambda: False
    mock_client.voices.list.return_value = page

    result = server.list_voices(q="texas", limit=10)

    assert "next_page" not in result
    structured = _structured_content_for(result)
    assert structured["next_page"] is None
    assert structured["data"][0]["gender"] is None
    jsonschema.validate(instance=structured, schema=schema)


@patch("cartesia_mcp.server.client")
def test_list_voices_with_next_page_structured_output_validates(
    mock_client: MagicMock,
) -> None:
    schema = _list_voices_output_schema()
    page = MagicMock()
    page.data = [
        _voice(
            id="voice_xyz",
            description="catalog voice",
            is_owner=False,
            is_public=True,
            name="Jolene - Warm Storyteller",
            country="US",
            gender="feminine",
        )
    ]
    page.has_next_page = lambda: True
    mock_client.voices.list.return_value = page

    result = server.list_voices(gender="feminine", q="southern", limit=1)

    assert result["next_page"] == "voice_xyz"
    structured = _structured_content_for(result)
    jsonschema.validate(instance=structured, schema=schema)
