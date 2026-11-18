"""Hosted clients pass file_id; file_path is a path on this MCP server."""

from __future__ import annotations

import json
import logging
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
    mock_download.assert_called_once_with("file_abc")


def test_resolve_audio_input_keeps_server_path(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"audio")
    assert server._resolve_audio_input(str(clip), None) == str(clip.resolve())


def test_resolve_audio_input_missing_local_path() -> None:
    with pytest.raises(ValueError, match="does not exist"):
        server._resolve_audio_input("/no/such/clip.mp3", None)


def test_resolve_audio_input_missing_path_on_hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_is_hosted", True)
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input("/Users/dev/Desktop/clip.mp3", None)


def test_resolve_audio_input_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a file"):
        server._resolve_audio_input(str(tmp_path), None)


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
    mock_download.assert_called_once_with("file_abc")
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

    mock_download.assert_called_once_with("file_abc")
    assert mock_client.voices.clone.call_args.kwargs["name"] == "Test"


def _hosted_as(monkeypatch: pytest.MonkeyPatch, out: Path, credential: str) -> Path:
    """Act as one hosted caller; return that caller's output directory."""
    monkeypatch.setattr(server, "_is_hosted", True)
    monkeypatch.setattr(server, "OUTPUT_DIRECTORY", str(out))
    monkeypatch.setattr(server, "resolve_api_credential", lambda: credential)
    caller_dir = Path(server._caller_output_directory())
    caller_dir.mkdir(parents=True, exist_ok=True)
    return caller_dir


def test_resolve_audio_input_hosted_accepts_output_directory_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    caller_dir = _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    clip = caller_dir / "text_to_speech_clip.wav"
    clip.write_bytes(b"audio")
    assert server._resolve_audio_input(str(clip), None) == str(clip.resolve())


def test_resolve_audio_input_hosted_rejects_another_callers_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alice_dir = _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    clip = alice_dir / "download_private_1234abcd.wav"
    clip.write_bytes(b"alice audio")
    _hosted_as(monkeypatch, tmp_path, "sk_car_mallory")
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(str(clip), None)
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(
            str(Path(server._caller_output_directory()) / ".." / alice_dir.name / clip.name),
            None,
        )


def test_resolve_audio_input_hosted_rejects_another_callers_file_via_proc_fd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """/proc/self/fd/N must not smuggle another caller's file past the directory check.

    While a victim's STT upload or stream has their file open, the fd link
    resolves to the victim's path. resolve(strict=True) follows it, so the
    file must land inside the caller's own directory or be rejected.
    """
    victim_dir = _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    clip = victim_dir / "download_private_1234abcd.wav"
    clip.write_bytes(b"alice audio")
    with open(clip, "rb") as open_clip:
        _hosted_as(monkeypatch, tmp_path, "sk_car_mallory")
        with pytest.raises(ValueError, match="file_id"):
            server._resolve_audio_input(f"/proc/self/fd/{open_clip.fileno()}", None)


def test_resolve_audio_input_hosted_rejects_shared_root_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Files left in the shared root by older versions are nobody's to read."""
    _hosted_as(monkeypatch, tmp_path, "sk_car_mallory")
    legacy = tmp_path / "text_to_speech_2026-11-14_00-00-00_deadbeef.wav"
    legacy.write_bytes(b"audio")
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(str(legacy), None)


def test_hosted_writes_land_in_caller_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alice_dir = _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    written = Path(server._write_audio_output(b"RIFF", "text_to_speech", "wav"))
    assert written.parent == alice_dir
    assert "sk_car_alice" not in str(written)
    assert server._resolve_audio_input(str(written), None) == str(written.resolve())

    _hosted_as(monkeypatch, tmp_path, "sk_car_mallory")
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(str(written), None)


@pytest.mark.parametrize("path", ["/etc/hostname", "/proc/self/environ"])
def test_resolve_audio_input_hosted_rejects_paths_outside_output_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, path: str
) -> None:
    _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(path, None)


def test_resolve_audio_input_hosted_rejects_traversal_and_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    out = _hosted_as(monkeypatch, tmp_path / "out", "sk_car_alice")
    (out / "link.wav").symlink_to(secret)
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(str(out / ".." / "secret.txt"), None)
    with pytest.raises(ValueError, match="file_id"):
        server._resolve_audio_input(str(out / "link.wav"), None)


def test_resolve_audio_input_hosted_rejects_output_directory_itself(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    caller_dir = _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    for directory in (tmp_path, caller_dir):
        with pytest.raises(ValueError, match="file_id"):
            server._resolve_audio_input(str(directory), None)


def _hosted_audio_input_log(caplog: pytest.LogCaptureFixture) -> dict[str, str]:
    records = [r for r in caplog.records if r.name == "cartesia_mcp.mcp"]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert isinstance(payload, dict)
    return payload


def test_hosted_file_path_log_accepts_output_directory_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caller_dir = _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    clip = caller_dir / "text_to_speech_clip.wav"
    clip.write_bytes(b"audio")
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        server._resolve_audio_input(str(clip), None, tool="speech_to_text")
    payload = _hosted_audio_input_log(caplog)
    assert payload == {
        "event": "mcp_audio_input",
        "class": "caller_file",
        "result": "accept",
        "tool": "speech_to_text",
    }
    assert str(clip) not in caplog.text


@pytest.mark.parametrize("path", ["/etc/hostname", "/proc/self/environ"])
def test_hosted_file_path_log_rejects_server_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    path: str,
) -> None:
    _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        with pytest.raises(ValueError, match="file_id"):
            server._resolve_audio_input(path, None, tool="clone_voice")
    payload = _hosted_audio_input_log(caplog)
    assert payload["class"] == "server_sensitive"
    assert payload["result"] == "reject"
    assert payload["tool"] == "clone_voice"
    assert path not in payload.values()


def test_hosted_file_path_log_rejects_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    caller_dir = _hosted_as(monkeypatch, tmp_path / "out", "sk_car_alice")
    (caller_dir / "link.wav").symlink_to(secret)
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        with pytest.raises(ValueError, match="file_id"):
            server._resolve_audio_input(
                str(caller_dir / ".." / "secret.txt"), None, tool="speech_to_text"
            )
    assert _hosted_audio_input_log(caplog)["class"] == "traversal"
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        with pytest.raises(ValueError, match="file_id"):
            server._resolve_audio_input(
                str(caller_dir / "link.wav"), None, tool="speech_to_text"
            )
    assert _hosted_audio_input_log(caplog)["class"] == "traversal"
    assert "secret.txt" not in caplog.text


def test_hosted_file_path_log_rejects_client_and_missing_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _hosted_as(monkeypatch, tmp_path, "sk_car_alice")
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        with pytest.raises(ValueError, match="file_id"):
            server._resolve_audio_input(
                "/Users/dev/Desktop/clip.mp3", None, tool="speech_to_text"
            )
    assert _hosted_audio_input_log(caplog)["class"] == "client_local"
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        with pytest.raises(ValueError, match="file_id"):
            server._resolve_audio_input("/no/such/clip.mp3", None, tool="speech_to_text")
    assert _hosted_audio_input_log(caplog)["class"] == "missing"


def test_hosted_file_path_class_other_tenant(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    caller_root = output_root / "t_alice"
    caller_root.mkdir(parents=True)
    other = output_root / "t_mallory" / "clip.wav"
    other.parent.mkdir()
    other.write_bytes(b"audio")
    assert (
        server._hosted_file_path_class(
            other,
            output_root=output_root.resolve(),
            caller_root=caller_root.resolve(),
        )
        == "other_tenant"
    )


def test_stdio_file_path_does_not_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(server, "_is_hosted", False)
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"audio")
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        assert server._resolve_audio_input(str(clip), None, tool="speech_to_text") == str(
            clip.resolve()
        )
    assert "mcp_audio_input" not in caplog.text
