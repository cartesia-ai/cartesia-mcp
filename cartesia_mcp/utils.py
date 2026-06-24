import os
import datetime
import typing
import wave
from pathlib import Path

from cartesia.stt.types.stt_encoding import SttEncoding
from cartesia_mcp.custom_types import (
    ListPronunciationDictsResult,
    ListVoicesResult,
    ToolType,
)
from cartesia.core.pagination import SyncPager
from cartesia.core.request_options import RequestOptions
from cartesia.voice_changer.types import OutputFormatContainer
from cartesia.voices.types import Voice

_BYTES_PER_SAMPLE: dict[SttEncoding, int] = {
    "pcm_s16le": 2,
    "pcm_s32le": 4,
    "pcm_f16le": 2,
    "pcm_f32le": 4,
    "pcm_mulaw": 1,
    "pcm_alaw": 1,
}


def _wav_encoding(sample_width: int) -> SttEncoding:
    if sample_width == 2:
        return "pcm_s16le"
    if sample_width == 4:
        return "pcm_s32le"
    raise ValueError(
        f"Unsupported WAV sample width {sample_width} bytes (expected 2 or 4)."
    )


def _read_pcm_chunks(file_path: str, *, encoding: SttEncoding, sample_rate: int) -> typing.Iterator[bytes]:
    bytes_per_sample = _BYTES_PER_SAMPLE[encoding]
    chunk_bytes = max(sample_rate * bytes_per_sample // 10, 1)

    def _iter() -> typing.Iterator[bytes]:
        with open(file_path, "rb") as audio_file:
            while chunk := audio_file.read(chunk_bytes):
                yield chunk

    return _iter()


def _read_wav_chunks(file_path: str) -> tuple[SttEncoding, int, typing.Iterator[bytes]]:
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
    encoding: typing.Optional[SttEncoding] = None,
    sample_rate: typing.Optional[int] = None,
) -> tuple[SttEncoding, int, typing.Iterator[bytes]]:
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


def create_output_file(output_directory: str, tool_type: ToolType,
                       extension: OutputFormatContainer) -> Path:
    dir_path = Path(output_directory)

    dir_path.mkdir(parents=True, exist_ok=True)

    if not os.access(dir_path, os.W_OK):
        raise Exception(
            f"Output directory {dir_path} is not writable")

    return dir_path / f"{tool_type}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.{extension}"


def build_list_voices_request_options(
    request_options: typing.Optional[RequestOptions],
    *,
    language: typing.Optional[str] = None,
    q: typing.Optional[str] = None,
    expand: typing.Optional[typing.Sequence[str]] = None,
) -> typing.Optional[RequestOptions]:
    extra_query: dict[str, typing.Any] = {}
    if language is not None:
        extra_query["language"] = language
    if q is not None:
        extra_query["q"] = q
    if expand:
        extra_query["expand[]"] = list(expand)
    if not extra_query:
        return request_options

    merged: RequestOptions = dict(request_options or {})
    base = dict(merged.get("additional_query_parameters") or {})
    base.update(extra_query)
    merged["additional_query_parameters"] = base
    return merged


def voice_list_page_to_result(pager: SyncPager[Voice]) -> ListVoicesResult:
    data = [voice.model_dump(mode="json") for voice in pager.items]
    result: ListVoicesResult = {"data": data, "has_more": pager.has_next}
    if pager.has_next and data:
        result["next_page"] = data[-1]["id"]
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
