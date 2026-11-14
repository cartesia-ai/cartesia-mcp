"""Listed output schemas drop titles and string enums but keep their shape."""

from __future__ import annotations

import asyncio
import json

import jsonschema

import cartesia_mcp.server as server
from cartesia_mcp.mcpserver import compact_output_schema


def _listed_output_schemas() -> dict[str, dict]:
    tools = asyncio.run(server.mcp.list_tools())
    return {t.name: t.output_schema for t in tools if t.output_schema is not None}


def test_compact_drops_titles_and_string_enums() -> None:
    schema = {
        "title": "Voice",
        "type": "object",
        "properties": {
            "title": {"title": "Title", "type": "string"},
            "language": {
                "anyOf": [{"enum": ["en", "fr"], "type": "string"}, {"type": "string"}],
                "title": "Language",
            },
            "gender": {
                "anyOf": [{"enum": ["masculine"], "type": "string"}, {"type": "null"}],
                "default": None,
            },
        },
        "required": ["title", "language"],
    }
    assert compact_output_schema(schema) == {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "language": {"type": "string"},
            "gender": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        },
        "required": ["title", "language"],
    }


def test_listed_output_schemas_have_no_titles_or_enums() -> None:
    for name, schema in _listed_output_schemas().items():
        dumped = json.dumps(schema)
        assert '"enum"' not in dumped, name
        assert '"title": "' not in dumped.replace('"title": {', ""), name


def test_listed_voice_schema_accepts_new_accent_values() -> None:
    schema = _listed_output_schemas()["get_voice"]
    voice = {
        "id": "voice_abc",
        "access": "private",
        "created_at": "2026-11-14T00:00:00Z",
        "description": "",
        "is_owner": True,
        "language": "en",
        "locales": [{"locale": "en-US", "is_native": True}],
        "name": "Test",
        "tagline": "",
        "visibility": "owner",
        "accent": "accent-added-after-this-sdk",
    }
    jsonschema.validate(voice, schema)
    del voice["name"]
    try:
        jsonschema.validate(voice, schema)
    except jsonschema.ValidationError:
        pass
    else:
        raise AssertionError("required fields must still be enforced")
