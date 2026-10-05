"""Hosted clients pass file_id; file_path is a path on this MCP server."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

import cartesia_mcp.server as server


def test_resolve_audio_input_requires_exactly_one() -> None:
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(None, None)
    with pytest.raises(ValueError, match="not both"):
        server._resolve_audio_input("/tmp/clip.mp3", "file_abc")
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input("  ", "  ")


@patch("cartesia_mcp.server._cloud_file_on_disk", return_value=(Path("/tmp/clip.wav"), "clip.wav"))
def test_resolve_audio_input_downloads_file_id(mock_download: MagicMock) -> None:
    assert server._resolve_audio_input(None, " file_abc ") == "/tmp/clip.wav"
    mock_download.assert_called_once_with("file_abc", request_options=None)


def test_resolve_audio_input_keeps_server_path() -> None:
    assert server._resolve_audio_input("/tmp/clip.mp3", None) == "/tmp/clip.mp3"


@patch("cartesia_mcp.server.save_downloaded_file", return_value=Path("/tmp/download_out.wav"))
@patch("cartesia_mcp.server.extra_api.download_file_bytes", return_value=b"audio")
@patch("cartesia_mcp.server.extra_api.get_file_info", return_value={"filename": "out.wav"})
def test_cloud_file_on_disk_keeps_extension(
    _info: MagicMock,
    _bytes: MagicMock,
    save: MagicMock,
) -> None:
    path, filename = server._cloud_file_on_disk("file_abc")
    assert path == Path("/tmp/download_out.wav")
    assert filename == "out.wav"
    assert save.call_args.kwargs["filename"] == "out.wav"


@patch("cartesia_mcp.server.client")
@patch("cartesia_mcp.server._cloud_file_on_disk", return_value=(Path("/tmp/clip.mp3"), "clip.mp3"))
def test_speech_to_text_accepts_file_id(mock_download: MagicMock, mock_client: MagicMock) -> None:
    mock_client.stt.transcribe.return_value = MagicMock(text="hello")

    with patch("builtins.open", mock_open(read_data=b"audio")) as opened:
        result = server.speech_to_text(file_id="file_abc", language="en")

    assert result.text == "hello"
    mock_download.assert_called_once_with("file_abc", request_options=None)
    opened.assert_called_once_with("/tmp/clip.mp3", "rb")


@patch("cartesia_mcp.server.client")
@patch("cartesia_mcp.server._cloud_file_on_disk", return_value=(Path("/tmp/clip.wav"), "clip.wav"))
def test_clone_voice_accepts_file_id(mock_download: MagicMock, mock_client: MagicMock) -> None:
    mock_client.voices.clone.return_value = MagicMock(id="voice_new")

    with patch("builtins.open", mock_open(read_data=b"clip")):
        server.clone_voice(
            name="Test",
            language="en",
            mode="similarity",
            file_id="file_abc",
        )

    mock_download.assert_called_once_with("file_abc", request_options=None)
    assert mock_client.voices.clone.call_args.kwargs["name"] == "Test"
