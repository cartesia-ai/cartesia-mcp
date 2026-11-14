import asyncio

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
    assert {"generate_and_transcribe", "clone_and_localize"} <= prompts


def test_generate_and_transcribe_prompt_mentions_tools() -> None:
    text = server.generate_and_transcribe("Hello there", voice="Katie")
    assert "text_to_speech" in text and "speech_to_text" in text and "'Katie'" in text


def test_discarding_sdk_client_keeps_shared_http_client_open() -> None:
    import gc

    create_cartesia_client("sk_car_test_c")
    gc.collect()
    assert not shared_http_client().is_closed
