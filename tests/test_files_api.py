from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.server as server


@pytest.fixture
def prod_files_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_FILES_BASE_URL", raising=False)


@patch("cartesia_mcp.server.client")
def test_list_files_forwards_query_params(
    mock_client: MagicMock,
    prod_files_base_url: None,
) -> None:
    mock_client.get.return_value = {"data": [], "has_more": False}

    server.list_files(limit=5, purpose="tts_generation", query="demo")

    mock_client.get.assert_called_once()
    args, kwargs = mock_client.get.call_args
    assert args[0] == extra_api._files_url("/files")
    assert kwargs["options"] == {
        "params": {"limit": "5", "purpose": "tts_generation", "q": "demo"},
    }


@patch("cartesia_mcp.server.client")
def test_get_file_calls_info_endpoint(
    mock_client: MagicMock,
    prod_files_base_url: None,
) -> None:
    mock_client.get.return_value = {"id": "file_abc", "filename": "clip.wav"}

    result = server.get_file("file_abc")

    mock_client.get.assert_called_once()
    args, _kwargs = mock_client.get.call_args
    assert args[0] == extra_api._files_url("/files/file_abc/info")
    assert result["filename"] == "clip.wav"


@patch("cartesia_mcp.server.save_downloaded_file")
@patch("cartesia_mcp.server.extra_api.download_file_bytes")
@patch("cartesia_mcp.server.extra_api.get_file_info")
@patch("cartesia_mcp.server.client")
def test_download_file_writes_to_output_directory(
    mock_client: MagicMock,
    mock_get_file_info: MagicMock,
    mock_download_bytes: MagicMock,
    mock_save: MagicMock,
) -> None:
    _ = mock_client
    mock_get_file_info.return_value = {
        "id": "file_abc",
        "filename": "tts-output.pcm",
    }
    mock_download_bytes.return_value = b"audio-bytes"
    mock_save.return_value = Path("/tmp/download_tts-output.wav")

    result = server.download_file("file_abc", format="playback")

    mock_get_file_info.assert_called_once_with(mock_client, "file_abc")
    mock_download_bytes.assert_called_once_with(
        mock_client,
        "file_abc",
        format="playback",
    )
    mock_save.assert_called_once_with(
        server.OUTPUT_DIRECTORY,
        file_id="file_abc",
        filename="tts-output.wav",
        content=b"audio-bytes",
    )
    assert result == {
        "file_path": "/tmp/download_tts-output.wav",
        "file_id": "file_abc",
        "filename": "tts-output.wav",
    }


def test_files_base_url_defaults_to_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_FILES_BASE_URL", raising=False)
    assert extra_api.files_base_url() == extra_api.DEFAULT_FILES_BASE_URL


def test_files_base_url_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTESIA_FILES_BASE_URL", "https://files.staging.example")
    assert extra_api.files_base_url() == "https://files.staging.example"


def test_save_downloaded_file_uses_safe_filename(tmp_path) -> None:
    from cartesia_mcp.utils import save_downloaded_file

    output = save_downloaded_file(
        str(tmp_path),
        file_id="file_abc",
        filename="../evil/name.wav",
        content=b"data",
    )

    assert output.parent == tmp_path
    assert output.name == "download_name.wav"
    assert output.read_bytes() == b"data"


def test_resolve_local_download_filename_playback_uses_wav() -> None:
    from cartesia_mcp.utils import resolve_local_download_filename

    assert resolve_local_download_filename("tts-output.pcm", "file_abc") == "tts-output.pcm"
    assert (
        resolve_local_download_filename("tts-output.pcm", "file_abc", as_wav=True)
        == "tts-output.wav"
    )
    assert resolve_local_download_filename("noext", "file_abc", as_wav=True) == "noext.wav"


def test_save_downloaded_file_playback_pcm_saved_as_wav(tmp_path) -> None:
    from cartesia_mcp.utils import resolve_local_download_filename, save_downloaded_file

    local_name = resolve_local_download_filename("generation.pcm", "file_abc", as_wav=True)
    output = save_downloaded_file(
        str(tmp_path),
        file_id="file_abc",
        filename=local_name,
        content=b"RIFF....WAVE",
    )

    assert output.suffix == ".wav"
    assert output.name == "download_generation.wav"
