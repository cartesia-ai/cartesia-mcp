from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.server as server


@pytest.fixture
def prod_files_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_FILES_BASE_URL", raising=False)


@patch("cartesia_mcp.server.save_downloaded_file")
@patch("cartesia_mcp.server.extra_api.create_file_download_link")
@patch("cartesia_mcp.server.extra_api.download_file_bytes")
@patch("cartesia_mcp.server.extra_api.get_file_info")
@patch("cartesia_mcp.server.client")
def test_download_file_returns_url_and_local_path(
    mock_client: MagicMock,
    mock_get_file_info: MagicMock,
    mock_download_bytes: MagicMock,
    mock_create_link: MagicMock,
    mock_save: MagicMock,
) -> None:
    _ = mock_client
    mock_get_file_info.return_value = {
        "id": "file_abc",
        "filename": "tts-output.pcm",
    }
    mock_download_bytes.return_value = b"audio-bytes"
    mock_create_link.return_value = "https://files.cartesia.ai/link/link_abc"
    mock_save.return_value = Path("/tmp/download_tts-output.wav")

    result = server.download_file("file_abc", format="playback")

    mock_get_file_info.assert_called_once_with(mock_client, "file_abc")
    mock_download_bytes.assert_called_once_with(
        mock_client,
        "file_abc",
        format="playback",
    )
    mock_create_link.assert_called_once_with(mock_client, "file_abc")
    mock_save.assert_called_once_with(
        server.OUTPUT_DIRECTORY,
        file_id="file_abc",
        filename="tts-output.wav",
        content=b"audio-bytes",
    )
    assert result == {
        "file_id": "file_abc",
        "download_url": "https://files.cartesia.ai/link/link_abc?format=playback",
        "file_path": "/tmp/download_tts-output.wav",
        "filename": "tts-output.wav",
    }


@patch("cartesia_mcp.server._cloud_download_url")
@patch("cartesia_mcp.server.client")
def test_text_to_speech_save_returns_cloud_ids(
    mock_client: MagicMock,
    mock_cloud_url: MagicMock,
) -> None:
    mock_response = MagicMock()
    mock_response.read.return_value = b"audio-bytes"
    mock_response.headers = {"Cartesia-File-ID": "file_new"}
    mock_client.tts.generate.return_value = mock_response
    mock_cloud_url.return_value = "https://files.cartesia.ai/link/link_new"

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice={"mode": "id", "id": "voice_abc"},
            output_format={"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100},
            save=True,
        )

    mock_client.tts.generate.assert_called_once()
    assert mock_client.tts.generate.call_args.kwargs["save"] is True
    mock_cloud_url.assert_called_once_with("file_new")
    assert result == {
        "file_id": "file_new",
        "download_url": "https://files.cartesia.ai/link/link_new",
        "file_path": "/tmp/out.wav",
    }


@patch("cartesia_mcp.server.client")
def test_text_to_speech_without_save_returns_local_path_only(
    mock_client: MagicMock,
) -> None:
    mock_response = MagicMock()
    mock_response.read.return_value = b"audio-bytes"
    mock_response.headers = {}
    mock_client.tts.generate.return_value = mock_response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice={"mode": "id", "id": "voice_abc"},
            output_format={"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100},
            save=False,
        )

    assert "save" not in mock_client.tts.generate.call_args.kwargs
    assert result == {"file_path": "/tmp/out.wav"}


def test_files_base_url_defaults_to_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_FILES_BASE_URL", raising=False)
    assert extra_api.files_base_url() == extra_api.DEFAULT_FILES_BASE_URL


def test_files_base_url_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTESIA_FILES_BASE_URL", "https://files.staging.example")
    assert extra_api.files_base_url() == "https://files.staging.example"


def test_file_id_from_response_headers_is_case_insensitive() -> None:
    assert extra_api.file_id_from_response_headers(
        {"Cartesia-File-ID": "file_abc"},
    ) == "file_abc"
    assert extra_api.file_id_from_response_headers(
        {"cartesia-file-id": "file_xyz"},
    ) == "file_xyz"


def test_with_download_format_appends_query() -> None:
    assert extra_api.with_download_format(
        "https://files.cartesia.ai/link/link_abc",
        "playback",
    ) == "https://files.cartesia.ai/link/link_abc?format=playback"


@patch("cartesia_mcp.extra_api._files_url")
def test_create_file_download_link_posts_lifetime(
    mock_files_url: MagicMock,
) -> None:
    mock_client = MagicMock()
    mock_files_url.return_value = "https://files.cartesia.ai/links"
    mock_client.post.return_value = {"url": "https://files.cartesia.ai/link/link_abc"}

    url = extra_api.create_file_download_link(mock_client, "file_abc", lifetime_hours=24)

    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://files.cartesia.ai/links"
    assert kwargs["body"] == {"file_id": "file_abc", "lifetime": "24h"}
    assert url == "https://files.cartesia.ai/link/link_abc"


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
