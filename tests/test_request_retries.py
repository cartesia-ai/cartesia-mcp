"""Verify request retry overrides using the SDK's real HTTP retry loop."""

from unittest.mock import patch

import httpx
import pytest
from cartesia import Cartesia, InternalServerError

import cartesia_mcp.server as server


@pytest.mark.parametrize("max_retries, expected_requests", [(0, 1), (1, 2), (None, 3)])
@pytest.mark.parametrize(
    "tool, arguments",
    [
        (server.list_voices, {}),
        (server.get_voice, {"voice_id": "test-voice"}),
        (server.delete_voice, {"voice_id": "test-voice"}),
        (
            server.update_voice,
            {"voice_id": "test-voice", "name": "Updated", "description": "test"},
        ),
        (server.list_accents, {}),
        (server.add_voice_accents, {"voice_id": "test-voice", "accents": ["british"]}),
        (server.delete_voice_accent, {"voice_id": "test-voice", "accent": "british"}),
        (
            server.localize_voice,
            {
                "voice_id": "test-voice",
                "name": "Localized",
                "description": "test",
                "accent": "british",
                "language": "en",
                "original_speaker_gender": "male",
            },
        ),
        (
            server.text_to_speech,
            {
                "voice_id": "test-voice",
                "transcript": "Hello",
                "output_format": {
                    "container": "wav",
                    "encoding": "pcm_s16le",
                    "sample_rate": 16000,
                },
            },
        ),
        (
            server.clone_voice,
            {"name": "Clone", "language": "en", "mode": "similarity"},
        ),
        (server.speech_to_text, {}),
    ],
)
def test_http_tools_honor_request_retry_limit(
    tmp_path, max_retries, expected_requests, tool, arguments
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"error": "unavailable"})

    arguments = dict(arguments)
    if tool in (server.clone_voice, server.speech_to_text):
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"test audio")
        arguments["file_path"] = str(audio)
    options = {} if max_retries is None else {"max_retries": max_retries}
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        sdk = Cartesia(api_key="test-key", http_client=http_client)
        with (
            patch.object(server, "client", sdk),
            patch("cartesia._base_client.time.sleep"),
        ):
            with pytest.raises(InternalServerError):
                tool(**arguments, request_options=options)
        assert len(requests) == expected_requests
        assert (
            sdk.max_retries == 2
        )  # Per-call overrides must not change the shared client.


def test_retry_override_preserves_headers_and_returns_recovered_response() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"data": [], "has_more": False})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        sdk = Cartesia(api_key="test-key", http_client=http_client)
        with (
            patch.object(server, "client", sdk),
            patch("cartesia._base_client.time.sleep"),
        ):
            result = server.list_voices(
                request_options={"max_retries": 1, "headers": {"X-Trace": "test-trace"}}
            )
        assert result == {"data": [], "has_more": False}
        assert len(requests) == 2
        assert all(request.headers["X-Trace"] == "test-trace" for request in requests)
        assert sdk.max_retries == 2
