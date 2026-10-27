"""Local text_to_speech output_path writes into the caller's chosen file."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import cartesia_mcp.server as server


def _wav_format() -> dict[str, object]:
    return {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}


@patch("cartesia_mcp.server.client")
def test_text_to_speech_output_path_writes_file(
    mock_client: MagicMock,
    tmp_path: Path,
) -> None:
    mock_response = MagicMock(read=lambda: b"audio-bytes")
    mock_response.headers = {}
    mock_client.tts.generate.return_value = mock_response
    dest = tmp_path / "assets" / "click.wav"

    result = server.text_to_speech(
        transcript="Hello",
        voice_id="voice_abc",
        output_format=_wav_format(),
        output_path=str(dest),
        save=False,
    )

    assert dest.read_bytes() == b"audio-bytes"
    assert result == {"file_path": str(dest.resolve())}


@patch("cartesia_mcp.server.client")
def test_text_to_speech_output_path_relative_to_cwd(
    mock_client: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_response = MagicMock(read=lambda: b"rel-audio")
    mock_response.headers = {}
    mock_client.tts.generate.return_value = mock_response
    monkeypatch.chdir(tmp_path)

    result = server.text_to_speech(
        transcript="Hello",
        voice_id="voice_abc",
        output_format=_wav_format(),
        output_path="out/hello.wav",
        save=False,
    )

    dest = (tmp_path / "out" / "hello.wav").resolve()
    assert dest.read_bytes() == b"rel-audio"
    assert result == {"file_path": str(dest)}


@patch("cartesia_mcp.server.client")
def test_text_to_speech_output_path_rejected_on_hosted(
    mock_client: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "_is_hosted", True)

    with pytest.raises(ValueError, match="local Cartesia MCP"):
        server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            output_path=str(tmp_path / "click.wav"),
            save=False,
        )

    mock_client.tts.generate.assert_not_called()


@patch("cartesia_mcp.server.client")
def test_text_to_speech_output_path_rejects_directory(
    mock_client: MagicMock,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="directory"):
        server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            output_path=str(tmp_path),
            save=False,
        )

    mock_client.tts.generate.assert_not_called()
