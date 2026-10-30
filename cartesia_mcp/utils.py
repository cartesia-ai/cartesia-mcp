import datetime
import json
import logging
import os
import tempfile
import threading
import time
import typing
import uuid
import wave
from pathlib import Path

from cartesia.pagination import SyncCursorIDPage
from cartesia.types import OutputFormatContainer, STTEncoding, Voice
from cartesia_mcp.custom_types import (
    ListPronunciationDictsResult,
    ListVoicesResult,
    ToolType,
)
from cartesia_mcp.mcp_session_guard import report_output_directory_metrics

# Match hosted /mcp JSON request logs so Render/Datadog pick these up together.
logger = logging.getLogger("cartesia_mcp.mcp")

# Hosted MCP writes ephemeral copies for same-session file_path / STT inputs.
# Keep them off the container working dir and delete after a short TTL so Render
# ephemeral disk does not fill up.
DEFAULT_HOSTED_OUTPUT_DIRNAME = "cartesia-mcp"
DEFAULT_OUTPUT_FILE_TTL_SECONDS = 3600
DEFAULT_OUTPUT_CLEANUP_INTERVAL_SECONDS = 300
# Warn well under Render Standard's ~18GB ephemeral limit.
DEFAULT_OUTPUT_DIRECTORY_WARN_BYTES = 2 * 1024 * 1024 * 1024

_cleanup_stop = threading.Event()
_cleanup_thread: threading.Thread | None = None


def default_output_directory(*, hosted: bool) -> str:
    """Resolve ``OUTPUT_DIRECTORY``: env wins; hosted defaults under the system temp dir."""
    env = os.getenv("OUTPUT_DIRECTORY")
    if env is not None and env.strip():
        return env.strip()
    if hosted:
        path = Path(tempfile.gettempdir()) / DEFAULT_HOSTED_OUTPUT_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return "."


def output_file_ttl_seconds() -> float:
    raw = os.getenv("OUTPUT_FILE_TTL_SECONDS")
    if raw is None or not raw.strip():
        return float(DEFAULT_OUTPUT_FILE_TTL_SECONDS)
    return max(float(raw), 60.0)


def output_directory_warn_bytes() -> int:
    raw = os.getenv("OUTPUT_DIRECTORY_WARN_BYTES")
    if raw is None or not raw.strip():
        return DEFAULT_OUTPUT_DIRECTORY_WARN_BYTES
    return max(int(raw), 0)


def measure_output_directory(directory: str) -> tuple[int, int]:
    """Return ``(file_count, total_bytes)`` for regular files under ``directory``."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return 0, 0
    files = 0
    total_bytes = 0
    for path in dir_path.iterdir():
        if not path.is_file():
            continue
        try:
            total_bytes += path.stat().st_size
            files += 1
        except OSError:
            logger.debug("Could not stat output file %s", path, exc_info=True)
    return files, total_bytes


def purge_stale_output_files(
    directory: str,
    *,
    max_age_seconds: float,
    now: float | None = None,
) -> int:
    """Delete regular files in ``directory`` older than ``max_age_seconds``. Returns count removed."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - max_age_seconds
    removed = 0
    for path in dir_path.iterdir():
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            logger.debug("Could not purge output file %s", path, exc_info=True)
    return removed


def cleanup_output_directory(
    directory: str,
    *,
    max_age_seconds: float,
    now: float | None = None,
) -> dict[str, typing.Any]:
    """Purge stale files, emit JSON logs + DogStatsD gauges, return a stats dict."""
    files_before, bytes_before = measure_output_directory(directory)
    removed = purge_stale_output_files(
        directory,
        max_age_seconds=max_age_seconds,
        now=now,
    )
    files_after, bytes_after = measure_output_directory(directory)
    warn_bytes = output_directory_warn_bytes()

    fields: dict[str, typing.Any] = {
        "event": "mcp_output_cleanup",
        "directory": directory,
        "ttl_seconds": max_age_seconds,
        "files_before": files_before,
        "bytes_before": bytes_before,
        "removed": removed,
        "files_after": files_after,
        "bytes_after": bytes_after,
        "warn_bytes": warn_bytes,
    }
    # Always info so size is visible even on quiet intervals (no removals).
    logger.info(json.dumps(fields, separators=(",", ":")))

    if warn_bytes and bytes_after >= warn_bytes:
        logger.warning(
            json.dumps(
                {
                    "event": "mcp_output_disk_warn",
                    "directory": directory,
                    "files": files_after,
                    "bytes": bytes_after,
                    "warn_bytes": warn_bytes,
                },
                separators=(",", ":"),
            )
        )

    report_output_directory_metrics(
        files=files_after,
        total_bytes=bytes_after,
        purged=removed,
    )
    return fields


def start_output_directory_cleanup(
    directory: str,
    *,
    max_age_seconds: float | None = None,
    interval_seconds: float = DEFAULT_OUTPUT_CLEANUP_INTERVAL_SECONDS,
) -> None:
    """Daemon thread that periodically purges stale files under ``directory``."""
    global _cleanup_thread
    if _cleanup_thread is not None and _cleanup_thread.is_alive():
        return

    ttl = output_file_ttl_seconds() if max_age_seconds is None else max_age_seconds
    _cleanup_stop.clear()

    def _loop() -> None:
        while not _cleanup_stop.wait(interval_seconds):
            try:
                cleanup_output_directory(directory, max_age_seconds=ttl)
            except Exception:
                logger.exception("Output directory cleanup failed for %s", directory)

    # Run once at start so a long-lived process recovers after a restart mid-TTL.
    cleanup_output_directory(directory, max_age_seconds=ttl)
    _cleanup_thread = threading.Thread(
        target=_loop,
        name="cartesia-mcp-output-cleanup",
        daemon=True,
    )
    _cleanup_thread.start()


_BYTES_PER_SAMPLE: dict[STTEncoding, int] = {
    "pcm_s16le": 2,
    "pcm_s32le": 4,
    "pcm_f16le": 2,
    "pcm_f32le": 4,
    "pcm_mulaw": 1,
    "pcm_alaw": 1,
}


def _wav_encoding(sample_width: int) -> STTEncoding:
    if sample_width == 2:
        return "pcm_s16le"
    if sample_width == 4:
        return "pcm_s32le"
    raise ValueError(
        f"Unsupported WAV sample width {sample_width} bytes (expected 2 or 4)."
    )


def _read_pcm_chunks(file_path: str, *, encoding: STTEncoding, sample_rate: int) -> typing.Iterator[bytes]:
    bytes_per_sample = _BYTES_PER_SAMPLE[encoding]
    chunk_bytes = max(sample_rate * bytes_per_sample // 10, 1)

    def _iter() -> typing.Iterator[bytes]:
        with open(file_path, "rb") as audio_file:
            while chunk := audio_file.read(chunk_bytes):
                yield chunk

    return _iter()


def _read_wav_chunks(file_path: str) -> tuple[STTEncoding, int, typing.Iterator[bytes]]:
    with wave.open(file_path, "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError(f"WAV must be mono, got {wf.getnchannels()} channels.")
        if wf.getcomptype() != "NONE":
            raise ValueError(f"WAV must be uncompressed PCM, got {wf.getcomptype()!r}.")
        encoding = _wav_encoding(wf.getsampwidth())
        sample_rate = wf.getframerate()
        frames_per_chunk = max(sample_rate // 10, 1)

        def _iter() -> typing.Iterator[bytes]:
            with wave.open(file_path, "rb") as reader:
                while True:
                    data = reader.readframes(frames_per_chunk)
                    if not data:
                        break
                    yield data

        return encoding, sample_rate, _iter()


def iter_stt_audio_chunks(
    file_path: str,
    *,
    encoding: typing.Optional[STTEncoding] = None,
    sample_rate: typing.Optional[int] = None,
) -> tuple[STTEncoding, int, typing.Iterator[bytes]]:
    """Prepare PCM chunks for STT WebSocket streaming."""
    path = Path(file_path)
    if path.suffix.lower() == ".wav":
        return _read_wav_chunks(file_path)

    if encoding is not None and sample_rate is not None:
        if encoding not in _BYTES_PER_SAMPLE:
            raise ValueError(f"Unsupported encoding {encoding!r}.")
        return encoding, sample_rate, _read_pcm_chunks(
            file_path, encoding=encoding, sample_rate=sample_rate
        )

    raise ValueError(
        "Streaming STT requires a mono PCM WAV file, or raw PCM with encoding and sample_rate set."
    )


def resolve_local_download_filename(
    filename: str,
    file_id: str,
    *,
    as_wav: bool = False,
) -> str:
    """Basename for a downloaded file on disk."""
    safe_name = Path(filename).name.strip() or file_id
    if as_wav:
        return f"{Path(safe_name).stem}.wav"
    return safe_name


def save_downloaded_file(
    output_directory: str,
    *,
    file_id: str,
    filename: str,
    content: bytes,
) -> Path:
    dir_path = Path(output_directory)
    dir_path.mkdir(parents=True, exist_ok=True)

    if not os.access(dir_path, os.W_OK):
        raise Exception(f"Output directory {dir_path} is not writable")

    safe_name = Path(filename).name.strip() or file_id
    if not Path(safe_name).suffix:
        safe_name = f"{safe_name}.bin"

    # Always unique: concurrent offloaded download_file calls can race an
    # exists-check + second-granularity timestamp.
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    output_path = dir_path / f"download_{stem}_{uuid.uuid4().hex[:8]}{suffix}"

    with output_path.open("wb") as f:
        f.write(content)

    return output_path


def create_output_file(output_directory: str, tool_type: ToolType,
                       extension: OutputFormatContainer) -> Path:
    dir_path = Path(output_directory)

    dir_path.mkdir(parents=True, exist_ok=True)

    if not os.access(dir_path, os.W_OK):
        raise Exception(
            f"Output directory {dir_path} is not writable")

    # Include a uuid so concurrent offloaded tools in the same second don't
    # collide on the same path.
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return dir_path / f"{tool_type}_{stamp}_{uuid.uuid4().hex[:8]}.{extension}"


def cursor_page_to_result(page: SyncCursorIDPage[typing.Any]) -> dict[str, typing.Any]:
    data = [item.model_dump(mode="json") for item in page.data]
    result: dict[str, typing.Any] = {
        "data": data,
        "has_more": page.has_next_page(),
    }
    if page.has_next_page() and data:
        result["next_page"] = data[-1]["id"]
    return result


def coerce_null_voice_locales(voice: Voice) -> Voice:
    """Catalog voices often have ``locales: null``. Voice output schemas require an array."""
    if voice.locales is None:
        return voice.model_copy(update={"locales": []})
    return voice


def voice_list_page_to_result(page: SyncCursorIDPage[Voice]) -> ListVoicesResult:
    result = typing.cast(ListVoicesResult, cursor_page_to_result(page))
    for item in result["data"]:
        if item.get("locales") is None:
            item["locales"] = []
    return result


def pronunciation_dict_list_to_result(
    payload: dict[str, typing.Any],
) -> ListPronunciationDictsResult:
    result: ListPronunciationDictsResult = {
        "data": payload.get("data", []),
        "has_more": bool(payload.get("has_more", False)),
    }
    next_page = payload.get("next_page")
    if next_page:
        result["next_page"] = next_page
    elif result["has_more"] and result["data"]:
        result["next_page"] = result["data"][-1]["id"]
    return result
