from pathlib import Path
from unittest.mock import MagicMock, patch

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.server as server


@patch("cartesia_mcp.server.client")
def test_list_files_forwards_query_params(mock_client: MagicMock) -> None:
    mock_client.get.return_value = {"data": [], "has_more": False}

    server.list_files(limit=5, purpose="tts_generation", query="demo")

    mock_client.get.assert_called_once()
    args, kwargs = mock_client.get.call_args
    assert args[0] == "https://files.cartesia.ai/files"
    assert kwargs["options"] == {
        "params": {"limit": "5", "purpose": "tts_generation", "q": "demo"},
    }


@patch("cartesia_mcp.server.client")
def test_get_file_calls_info_endpoint(mock_client: MagicMock) -> None:
    mock_client.get.return_value = {"id": "file_abc", "filename": "clip.wav"}

    result = server.get_file("file_abc")

    mock_client.get.assert_called_once()
    args, _kwargs = mock_client.get.call_args
    assert args[0] == "https://files.cartesia.ai/files/file_abc/info"
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
    mock_save.return_value = Path("/tmp/download_tts-output.pcm")

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
        filename="tts-output.pcm",
        content=b"audio-bytes",
    )
    assert result == {
        "file_path": "/tmp/download_tts-output.pcm",
        "file_id": "file_abc",
        "filename": "tts-output.pcm",
    }


def test_files_base_url_defaults_to_prod() -> None:
    assert extra_api.files_base_url() == "https://files.cartesia.ai"


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
