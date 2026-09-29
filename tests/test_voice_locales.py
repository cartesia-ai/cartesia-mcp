"""Regression: catalog voices ship locales=null; Voice output schemas require an array."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import jsonschema
import pytest
from cartesia.types import Voice

import cartesia_mcp.server as server
from cartesia_mcp.utils import coerce_null_voice_locales


def _schema(tool_name: str) -> dict:
    tools = asyncio.run(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == tool_name)
    assert tool.output_schema is not None
    return tool.output_schema


def _tool(name: str):
    return next(t for t in server.mcp._tool_manager.list_tools() if t.name == name)


def _voice(*, locales: object) -> Voice:
    return Voice.model_construct(
        id="voice_abc",
        access="public",
        created_at=datetime.now(timezone.utc),
        description="catalog voice",
        is_owner=False,
        language="en",
        locales=locales,
        name="Jolene",
        tagline="",
        visibility="all",
    )


def _structured(tool_name: str, result: object) -> dict:
    converted = _tool(tool_name).fn_metadata.convert_result(result)
    assert converted.structured_content is not None
    return converted.structured_content


def test_output_schema_rejects_null_locales() -> None:
    voice = _voice(locales=None)
    structured = _structured("get_voice", voice)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=structured, schema=_schema("get_voice"))


def test_coerce_null_voice_locales_to_empty_list() -> None:
    coerced = coerce_null_voice_locales(_voice(locales=None))
    assert coerced.locales == []
    structured = _structured("get_voice", coerced)
    jsonschema.validate(instance=structured, schema=_schema("get_voice"))


def test_coerce_keeps_existing_locales() -> None:
    coerced = coerce_null_voice_locales(
        _voice(locales=[{"locale": "en-US", "is_native": True}])
    )
    assert len(coerced.locales) == 1
    assert coerced.locales[0].locale == "en-US"
    assert coerced.locales[0].is_native is True


@patch("cartesia_mcp.server.client")
def test_get_voice_null_locales_structured_output_validates(mock_client: MagicMock) -> None:
    mock_client.voices.get.return_value = _voice(locales=None)

    result = server.get_voice("voice_abc")

    assert result.locales == []
    structured = _structured("get_voice", result)
    jsonschema.validate(instance=structured, schema=_schema("get_voice"))


@patch("cartesia_mcp.server.client")
def test_list_voices_null_locales_become_empty_list(mock_client: MagicMock) -> None:
    page = MagicMock()
    page.data = [_voice(locales=None)]
    page.has_next_page = lambda: False
    mock_client.voices.list.return_value = page

    result = server.list_voices(limit=1)

    assert result["data"][0]["locales"] == []
    structured = _structured("list_voices", result)
    jsonschema.validate(instance=structured, schema=_schema("list_voices"))
