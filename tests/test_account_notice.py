"""text_to_speech passes on a Cartesia-Notice the API sends about the account."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.server as server

NOTICE = "90% of this month's free credits are used. Try Pro free for a month: https://play.cartesia.ai/pro-free-month"


def _wav_format() -> dict[str, object]:
    return {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}


def test_notice_header_is_case_insensitive_and_trimmed() -> None:
    assert extra_api.notice_from_response_headers({"Cartesia-Notice": f"  {NOTICE} "}) == NOTICE


def test_missing_or_blank_notice_is_none() -> None:
    assert extra_api.notice_from_response_headers({}) is None
    assert extra_api.notice_from_response_headers({"cartesia-notice": "   "}) is None


@patch("cartesia_mcp.server._try_create_download_link", return_value="https://files.cartesia.ai/link/l1")
@patch("cartesia_mcp.server.client")
def test_saved_generation_carries_the_notice(mock_client: MagicMock, _link: MagicMock) -> None:
    response = MagicMock(read=lambda: b"audio-bytes")
    response.headers = {"Cartesia-File-ID": "file_new", "Cartesia-Notice": NOTICE}
    mock_client.tts.generate.return_value = response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            save=True,
        )

    assert result["notice"] == NOTICE
    assert result["file_id"] == "file_new"


@patch("cartesia_mcp.server.client")
def test_unsaved_generation_carries_the_notice(mock_client: MagicMock) -> None:
    response = MagicMock(read=lambda: b"audio-bytes")
    response.headers = {"Cartesia-Notice": NOTICE}
    mock_client.tts.generate.return_value = response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            save=False,
        )

    assert result == {"file_path": "/tmp/out.wav", "notice": NOTICE}


@patch("cartesia_mcp.server.client")
def test_no_notice_leaves_the_result_unchanged(mock_client: MagicMock) -> None:
    response = MagicMock(read=lambda: b"audio-bytes")
    response.headers = {}
    mock_client.tts.generate.return_value = response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            save=False,
        )

    assert result == {"file_path": "/tmp/out.wav"}
