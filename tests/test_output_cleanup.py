"""Hosted output directory defaults and TTL purge."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import cartesia_mcp.server as server
from cartesia_mcp.utils import (
    DEFAULT_HOSTED_OUTPUT_DIRNAME,
    cleanup_output_directory,
    default_output_directory,
    measure_output_directory,
    purge_stale_output_files,
)


def test_default_output_directory_local_is_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OUTPUT_DIRECTORY", raising=False)
    assert default_output_directory(hosted=False) == "."


def test_default_output_directory_hosted_uses_temp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("OUTPUT_DIRECTORY", raising=False)
    monkeypatch.setattr(
        "cartesia_mcp.utils.tempfile.gettempdir",
        lambda: str(tmp_path),
    )
    path = Path(default_output_directory(hosted=True))
    assert path == tmp_path / DEFAULT_HOSTED_OUTPUT_DIRNAME
    assert path.is_dir()


def test_default_output_directory_env_wins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OUTPUT_DIRECTORY", str(tmp_path / "custom"))
    assert default_output_directory(hosted=True) == str(tmp_path / "custom")
    assert default_output_directory(hosted=False) == str(tmp_path / "custom")


def test_purge_stale_output_files_removes_old_only(tmp_path: Path) -> None:
    old = tmp_path / "old.wav"
    fresh = tmp_path / "fresh.wav"
    old.write_bytes(b"old")
    fresh.write_bytes(b"fresh")
    now = time.time()
    os.utime(old, (now - 7200, now - 7200))
    os.utime(fresh, (now - 10, now - 10))

    removed = purge_stale_output_files(str(tmp_path), max_age_seconds=3600, now=now)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_purge_skips_missing_directory(tmp_path: Path) -> None:
    assert purge_stale_output_files(str(tmp_path / "missing"), max_age_seconds=60) == 0


def test_measure_output_directory(tmp_path: Path) -> None:
    (tmp_path / "a.wav").write_bytes(b"12345")
    (tmp_path / "b.wav").write_bytes(b"ab")
    (tmp_path / "subdir").mkdir()
    assert measure_output_directory(str(tmp_path)) == (2, 7)


def test_cleanup_output_directory_logs_and_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    metrics: list[tuple[int, int, int]] = []

    def _capture(*, files: int, total_bytes: int, purged: int = 0) -> None:
        metrics.append((files, total_bytes, purged))

    monkeypatch.setattr(
        "cartesia_mcp.utils.report_output_directory_metrics",
        _capture,
    )
    monkeypatch.setenv("OUTPUT_DIRECTORY_WARN_BYTES", "4")

    old = tmp_path / "old.wav"
    fresh = tmp_path / "fresh.wav"
    old.write_bytes(b"old-audio")
    fresh.write_bytes(b"fresh!!")
    now = time.time()
    os.utime(old, (now - 7200, now - 7200))
    os.utime(fresh, (now - 10, now - 10))

    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        stats = cleanup_output_directory(
            str(tmp_path),
            max_age_seconds=3600,
            now=now,
        )

    assert stats["removed"] == 1
    assert stats["files_after"] == 1
    assert stats["bytes_after"] == len(b"fresh!!")
    assert metrics == [(1, len(b"fresh!!"), 1)]

    events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    assert any(e.get("event") == "mcp_output_cleanup" for e in events)
    warn = next(e for e in events if e.get("event") == "mcp_output_disk_warn")
    assert warn["bytes"] == len(b"fresh!!")
    assert warn["warn_bytes"] == 4


@patch("cartesia_mcp.server._try_create_download_link")
@patch("cartesia_mcp.server.client")
def test_hosted_text_to_speech_save_skips_local_write(
    mock_client: MagicMock,
    mock_cloud_url: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(server, "_is_hosted", True)
    monkeypatch.setattr(server, "OUTPUT_DIRECTORY", str(tmp_path))
    mock_response = MagicMock()
    mock_response.read.return_value = b"audio-bytes"
    mock_response.headers = {"Cartesia-File-ID": "file_new"}
    mock_client.tts.generate.return_value = mock_response
    mock_cloud_url.return_value = "https://files.cartesia.ai/link/link_new"

    with patch("cartesia_mcp.server._write_audio_output") as mock_write:
        result = server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format={
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": 44100,
            },
            save=True,
        )

    mock_write.assert_not_called()
    assert result == {
        "file_id": "file_new",
        "download_url": "https://files.cartesia.ai/link/link_new",
    }
    assert "file_path" not in result
    assert list(tmp_path.iterdir()) == []


@patch("cartesia_mcp.server.client")
def test_hosted_text_to_speech_save_false_still_writes(
    mock_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(server, "_is_hosted", True)
    monkeypatch.setattr(server, "OUTPUT_DIRECTORY", str(tmp_path))
    mock_response = MagicMock(read=lambda: b"audio-bytes")
    mock_response.headers = {}
    mock_client.tts.generate.return_value = mock_response

    result = server.text_to_speech(
        transcript="Hello",
        voice_id="voice_abc",
        output_format={
            "container": "wav",
            "encoding": "pcm_s16le",
            "sample_rate": 44100,
        },
        save=False,
    )

    assert "file_path" in result
    path = Path(result["file_path"])
    assert path.parent == tmp_path
    assert path.read_bytes() == b"audio-bytes"
