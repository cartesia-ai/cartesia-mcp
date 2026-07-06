from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

import cartesia_mcp.server as server
from cartesia.types.shared.word_timestamps import WordTimestamps
from cartesia.types.stt_transcribe_response import Word as SttWord


def test_stt_words_from_timestamps_flattens_word_timestamps() -> None:
    words = server._stt_words_from_timestamps(
        [WordTimestamps(words=["hello", "world"], start=[0.0, 0.5], end=[0.4, 1.0])]
    )
    assert words == [
        SttWord(word="hello", start=0.0, end=0.4),
        SttWord(word="world", start=0.5, end=1.0),
    ]


@patch("cartesia_mcp.server.client")
def test_text_to_speech_passes_duration_via_extra_body(mock_client: MagicMock) -> None:
    mock_response = MagicMock(read=lambda: b"audio")
    mock_response.headers = {"Cartesia-File-ID": "file_test"}
    mock_client.tts.generate.return_value = mock_response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"), patch(
        "cartesia_mcp.server._cloud_download_url",
        return_value="https://example.com/link",
    ):
        server.text_to_speech(
            transcript="hello",
            voice={"mode": "id", "id": "voice-id"},
            output_format={"container": "wav", "sample_rate": 44100},
            duration=12.5,
        )

    kwargs = mock_client.tts.generate.call_args.kwargs
    assert kwargs["extra_body"] == {"duration": 12.5}
    assert kwargs["save"] is True


@patch("cartesia_mcp.server.client")
def test_clone_voice_passes_mode_via_extra_body(mock_client: MagicMock) -> None:
    mock_client.voices.clone.return_value = MagicMock()

    with patch("builtins.open", mock_open(read_data=b"clip")):
        server.clone_voice(
            file_path="/tmp/clip.wav",
            name="Test Voice",
            language="en",
            mode="stability",
            description="desc",
        )

    kwargs = mock_client.voices.clone.call_args.kwargs
    assert kwargs["extra_body"] == {"mode": "stability"}


@patch("cartesia_mcp.server.client")
@patch("cartesia_mcp.server.iter_stt_audio_chunks")
def test_speech_to_text_stream_non_english_uses_manual_finalize(
    mock_iter_chunks: MagicMock,
    mock_client: MagicMock,
) -> None:
    mock_iter_chunks.return_value = ("pcm_s16le", 44100, iter([b"chunk"]))
    mock_connection = MagicMock()
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.__exit__.return_value = False
    mock_connection.__iter__.return_value = iter(
        [MagicMock(type="transcript", is_final=True, text="hola", language="es")]
    )
    mock_ws_manager = MagicMock()
    mock_ws_manager.__enter__.return_value = mock_connection
    mock_ws_manager.__exit__.return_value = False
    mock_client.stt.manual_finalize.websocket.return_value = mock_ws_manager

    result = server.speech_to_text("/tmp/sample.wav", mode="stream", language="es")

    assert result.text == "hola"
    mock_client.stt.manual_finalize.websocket.assert_called_once()
    websocket_kwargs = mock_client.stt.manual_finalize.websocket.call_args.kwargs
    assert websocket_kwargs["extra_query"] == {"language": "es"}
    mock_client.stt.auto_finalize.websocket.assert_not_called()


@patch("cartesia_mcp.server.client")
@patch("cartesia_mcp.server.iter_stt_audio_chunks")
def test_speech_to_text_stream_word_timestamps_use_manual_finalize(
    mock_iter_chunks: MagicMock,
    mock_client: MagicMock,
) -> None:
    mock_iter_chunks.return_value = ("pcm_s16le", 44100, iter([b"chunk"]))
    mock_connection = MagicMock()
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.__exit__.return_value = False
    mock_connection.__iter__.return_value = iter(
        [
            MagicMock(
                type="transcript",
                is_final=True,
                text="hello",
                duration=1.2,
                language="en",
                words=[
                    WordTimestamps(words=["hello"], start=[0.0], end=[0.5]),
                ],
            )
        ]
    )
    mock_ws_manager = MagicMock()
    mock_ws_manager.__enter__.return_value = mock_connection
    mock_ws_manager.__exit__.return_value = False
    mock_client.stt.manual_finalize.websocket.return_value = mock_ws_manager

    result = server.speech_to_text(
        "/tmp/sample.wav",
        mode="stream",
        timestamp_granularities=["word"],
    )

    assert result.text == "hello"
    assert result.duration == 1.2
    assert result.words == [SttWord(word="hello", start=0.0, end=0.5)]
    mock_client.stt.manual_finalize.websocket.assert_called_once()
    websocket_kwargs = mock_client.stt.manual_finalize.websocket.call_args.kwargs
    assert websocket_kwargs["extra_query"] == {"timestamp_granularities[]": "word"}
    mock_connection.send.assert_any_call("finalize")
    mock_connection.send.assert_any_call("close")
    mock_client.stt.auto_finalize.websocket.assert_not_called()
