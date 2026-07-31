"""Tests for local audio output path generation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from cartesia_mcp.utils import create_output_file, save_downloaded_file


def test_create_output_file_unique_under_concurrency(tmp_path):
    def _make_path(_: int):
        return create_output_file(str(tmp_path), "text_to_speech", "wav")

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(_make_path, range(32)))

    assert len({str(path) for path in paths}) == 32
    for path in paths:
        assert path.parent == tmp_path
        assert path.name.startswith("text_to_speech_")
        assert path.suffix == ".wav"


def test_save_downloaded_file_unique_under_concurrency(tmp_path):
    def _save(_: int):
        return save_downloaded_file(
            str(tmp_path),
            file_id="file_abc",
            filename="clip.wav",
            content=b"audio",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(_save, range(32)))

    assert len({str(path) for path in paths}) == 32
    for path in paths:
        assert path.parent == tmp_path
        assert path.name.startswith("download_clip_")
        assert path.suffix == ".wav"
        assert path.read_bytes() == b"audio"
