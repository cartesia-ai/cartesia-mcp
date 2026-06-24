from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

import cartesia_mcp.server as server


def test_resolve_stt_model_defaults() -> None:
    assert server._resolve_stt_model("batch", None) == "ink-whisper"
    assert server._resolve_stt_model("stream", None) == "ink-2"


def test_resolve_stt_model_override() -> None:
    assert server._resolve_stt_model("batch", "ink-2") == "ink-2"


@patch("cartesia_mcp.server.client")
def test_speech_to_text_batch_uses_transcribe(mock_client: MagicMock) -> None:
    mock_client.stt.transcribe.return_value = {"text": "hello"}

    with patch("builtins.open", mock_open(read_data=b"audio")):
        result = server.speech_to_text("/tmp/sample.mp3", mode="batch", language="en")

    assert result == {"text": "hello"}
    mock_client.stt.transcribe.assert_called_once()
    kwargs = mock_client.stt.transcribe.call_args.kwargs
    assert kwargs["model"] == "ink-whisper"
    assert kwargs["language"] == "en"


@patch("cartesia_mcp.server.client")
@patch("cartesia_mcp.server.iter_stt_audio_chunks")
def test_speech_to_text_stream_uses_websocket(
    mock_iter_chunks: MagicMock,
    mock_client: MagicMock,
) -> None:
    mock_iter_chunks.return_value = ("pcm_s16le", 44100, iter([b"chunk"]))
    mock_ws = MagicMock()
    mock_client.stt.websocket.return_value = mock_ws
    mock_ws.transcribe.return_value = [
        {"type": "transcript", "is_final": True, "text": "hello world"},
    ]

    result = server.speech_to_text("/tmp/sample.wav", mode="stream")

    assert result.text == "hello world"
    mock_client.stt.websocket.assert_called_once()
    mock_ws.transcribe.assert_called_once()
