"""Tests for local audio output path generation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from cartesia_mcp.utils import create_output_file


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
