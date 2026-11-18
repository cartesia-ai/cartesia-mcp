import asyncio
import re

import cartesia_mcp.agents as agents
import cartesia_mcp.server as server
from cartesia_mcp.sdk_setup import create_cartesia_client, shared_http_client


def test_sdk_clients_share_one_http_client() -> None:
    first = create_cartesia_client("sk_car_test_a")
    second = create_cartesia_client("sk_car_test_b")
    assert first._client is shared_http_client()
    assert second._client is shared_http_client()
    assert first.api_key != second.api_key


def test_prompts_registered() -> None:
    prompts = {p.name for p in asyncio.run(server.mcp.list_prompts())}
    assert {
        "generate_and_transcribe",
        "clone_and_localize",
        "create_voice_agent",
        "debug_agent_call",
    } <= prompts


TOOL_LIKE = re.compile(
    r"`((?:list|get|create|update|delete|attach|detach)_[a-z_]+)`"
)


def test_agent_guidance_only_names_registered_tools() -> None:
    tool_names = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    texts = [
        agents.create_voice_agent("a pizza ordering line"),
        agents.debug_agent_call("agent_1"),
        agents.debug_agent_call("agent_1", call_id="ac_1"),
    ]
    for text in texts:
        assert set(TOOL_LIKE.findall(text)) <= tool_names
    assert "'a pizza ordering line'" in texts[0]
    assert "'ac_1'" in texts[2]


def test_debug_agent_call_without_agent_id_names_no_empty_id() -> None:
    for text in (agents.debug_agent_call(call_id="ac_1"), agents.debug_agent_call()):
        assert "''" not in text


def test_generate_and_transcribe_prompt_mentions_tools() -> None:
    text = server.generate_and_transcribe("Hello there", voice="Katie")
    assert "text_to_speech" in text and "speech_to_text" in text and "'Katie'" in text


def test_discarding_sdk_client_keeps_shared_http_client_open() -> None:
    import gc

    create_cartesia_client("sk_car_test_c")
    gc.collect()
    assert not shared_http_client().is_closed
