"""MCP_TOOLSET=agents serves Managed Agents without speech generation (Claude directory)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from cartesia_mcp import server

# Tools in server.py that the agents-only server must not register.
SPEECH_TOOLS = frozenset(
    {
        "text_to_speech",
        "speech_to_text",
        "clone_voice",
        "localize_voice",
        "update_voice",
        "delete_voice",
        "add_voice_accents",
        "delete_voice_accent",
        "list_accents",
        "list_models",
        "download_file",
        "get_credit_usage",
        "list_pronunciation_dicts",
        "create_pronunciation_dict",
        "get_pronunciation_dict",
        "update_pronunciation_dict",
        "delete_pronunciation_dict",
    }
)

# Prints the agents-only server's surface; the toolset is fixed at import time.
_SCRIPT = """
import asyncio, json
from cartesia_mcp import server

async def main():
    try:
        await server.mcp.call_tool("text_to_speech", {"transcript": "hi"})
        tts_callable = True
    except Exception:
        tts_callable = False
    prompts = await server.mcp.list_prompts()
    print(json.dumps({
        "name": server.mcp.name,
        "instructions": server.mcp.instructions,
        "tools": [t.name for t in server.mcp._tool_manager.list_tools()],
        "prompts": [p.name for p in prompts],
        "tts_callable": tts_callable,
    }))

asyncio.run(main())
"""


@pytest.fixture(scope="module")
def agents_server() -> dict:
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env={**os.environ, "MCP_TOOLSET": "agents"},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


def test_agents_server_drops_only_speech_tools(agents_server: dict) -> None:
    full = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert SPEECH_TOOLS <= full, f"stale SPEECH_TOOLS: {sorted(SPEECH_TOOLS - full)}"
    assert set(agents_server["tools"]) == full - SPEECH_TOOLS


def test_agents_server_keeps_voice_lookup(agents_server: dict) -> None:
    assert {"list_voices", "get_voice", "create_agent"} <= set(agents_server["tools"])


def test_agents_server_rejects_speech_tool_calls(agents_server: dict) -> None:
    assert agents_server["tts_callable"] is False


def test_agents_server_prompts_and_branding(agents_server: dict) -> None:
    assert set(agents_server["prompts"]) == {"create_voice_agent", "debug_agent_call"}
    assert agents_server["name"] == "Cartesia Agents"
    assert "text to speech" not in agents_server["instructions"]
