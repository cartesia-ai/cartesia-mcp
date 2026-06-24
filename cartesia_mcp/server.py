"""
Cartesia MCP Server
"""

import os
import typing
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from cartesia_mcp.custom_types import (
    DeletePronunciationDictResult,
    DeleteVoiceResult,
    GeneratedAudioResult,
    ListPronunciationDictsResult,
    ListVoicesResult,
    PronunciationDictItemParams,
)
from cartesia.voices.requests import LocalizeDialectParams
from cartesia.voices.types import VoiceMetadata, GenderPresentation, Gender, CloneMode, Voice
from cartesia.voice_changer.types import OutputFormatContainer
from cartesia.tts.types import SupportedLanguage, RawEncoding
from cartesia.tts.requests import OutputFormatParams, TtsRequestVoiceSpecifierParams
from cartesia.tts.requests.generation_config import GenerationConfigParams
from cartesia.stt.types.stt_encoding import SttEncoding
from cartesia.stt.types.timestamp_granularity import TimestampGranularity
from cartesia.stt.types.transcription_response import TranscriptionResponse
from cartesia.core.request_options import RequestOptions

from cartesia_mcp.constants import DEFAULT_MODEL_ID
from cartesia_mcp import extra_api
from cartesia_mcp.extra_api import UsageInterval
from cartesia_mcp.config import ensure_admin_http, env_or_none, validate_api_keys
from cartesia_mcp.sdk_setup import create_cartesia_client, get_http
from cartesia_mcp.utils import (
    build_list_voices_request_options,
    create_output_file,
    iter_stt_audio_chunks,
    pronunciation_dict_list_to_result,
    voice_list_page_to_result,
)

load_dotenv()

CARTESIA_API_KEY, CARTESIA_ADMIN_API_KEY = validate_api_keys(
    env_or_none("CARTESIA_API_KEY"),
    env_or_none("CARTESIA_ADMIN_API_KEY"),
)

OUTPUT_DIRECTORY = os.getenv("OUTPUT_DIRECTORY", ".")

client = create_cartesia_client(CARTESIA_API_KEY)
http = get_http(client)
admin_http = (
    get_http(create_cartesia_client(CARTESIA_ADMIN_API_KEY))
    if CARTESIA_ADMIN_API_KEY
    else None
)
mcp = FastMCP("Cartesia")


def _require_admin_http():
    return ensure_admin_http(admin_http)


def _build_generation_config(
    *,
    speed: typing.Optional[float] = None,
    volume: typing.Optional[float] = None,
    emotion: typing.Optional[str] = None,
) -> typing.Optional[GenerationConfigParams]:
    if speed is None and volume is None and emotion is None:
        return None
    config: GenerationConfigParams = {}
    if speed is not None:
        config["speed"] = speed
    if volume is not None:
        config["volume"] = volume
    if emotion is not None:
        config["emotion"] = emotion
    return config

@mcp.tool(description="""
        Parameters
        ----------
        transcript : str

        voice : TtsRequestVoiceSpecifierParams

        output_format : OutputFormatParams

        model_id : str
            The ID of the model to use for the generation. See [Models](/build-with-cartesia/models) for available models.

        language : typing.Optional[SupportedLanguage]

        duration : typing.Optional[float]
            The maximum duration of the audio in seconds. You do not usually need to specify this.
            If the duration is not appropriate for the length of the transcript, the output audio may be truncated.

        speed : typing.Optional[float]
            Speech speed multiplier (0.6–1.5). Applies to Sonic 3+ via `generation_config`.

        volume : typing.Optional[float]
            Volume multiplier (0.5–2.0). Applies to Sonic 3+ via `generation_config`.

        emotion : typing.Optional[str]
            Emotional guidance for the generation (e.g. `neutral`, `excited`, `sad`). Applies to Sonic 3+.

        pronunciation_dict_id : typing.Optional[str]
            Pronunciation dictionary ID to apply for this generation only.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration. You can pass in configuration such as `chunk_size`, and more to customize the request and response.

          """)
def text_to_speech(
    transcript: str,
    voice: TtsRequestVoiceSpecifierParams,
    output_format: OutputFormatParams,
    model_id: typing.Optional[str] = DEFAULT_MODEL_ID,
    language: typing.Optional[SupportedLanguage] = None,
    duration: typing.Optional[float] = None,
    speed: typing.Optional[float] = None,
    volume: typing.Optional[float] = None,
    emotion: typing.Optional[str] = None,
    pronunciation_dict_id: typing.Optional[str] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> GeneratedAudioResult:
    generation_config = _build_generation_config(
        speed=speed,
        volume=volume,
        emotion=emotion,
    )
    tts_kwargs: dict[str, typing.Any] = {
        "transcript": transcript,
        "voice": voice,
        "output_format": output_format,
        "model_id": model_id,
        "language": language,
        "duration": duration,
        "request_options": request_options,
    }
    if generation_config is not None:
        tts_kwargs["generation_config"] = generation_config
    if pronunciation_dict_id is not None:
        tts_kwargs["pronunciation_dict_id"] = pronunciation_dict_id
    result = client.tts.bytes(**tts_kwargs)

    output_file = create_output_file(OUTPUT_DIRECTORY, "text_to_speech",
                                        output_format["container"])

    audio_bytes = b"".join(result)
    with output_file.open("wb") as f:
        f.write(audio_bytes)

    return GeneratedAudioResult(file_path=str(output_file))


@mcp.tool(description="""
        Takes an audio file of speech, and returns an audio file of speech spoken with the same intonation, but with a different voice.

        Parameters
        ----------
        file_path : str
            The absolute path to the audio file to change.

        voice_id : str

        output_format_container : OutputFormatContainer

        output_format_sample_rate : int

        output_format_encoding : typing.Optional[RawEncoding]
            Required for `raw` and `wav` containers.

        output_format_bit_rate : typing.Optional[int]
            Required for `mp3` containers.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration. You can pass in configuration such as `chunk_size`, and more to customize the request and response.
          
        """)
def voice_change(
    file_path: str,
    voice_id: str,
    output_format_container: OutputFormatContainer,
    output_format_sample_rate: int,
    output_format_encoding: typing.Optional[RawEncoding] = None,
    output_format_bit_rate: typing.Optional[int] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> GeneratedAudioResult:
    with open(file_path, "rb") as clip:
        result = client.voice_changer.bytes(
            clip=clip,
            voice_id=voice_id,
            output_format_container=output_format_container,
            output_format_sample_rate=output_format_sample_rate,
            output_format_encoding=output_format_encoding,
            output_format_bit_rate=output_format_bit_rate,
            request_options=request_options,
        )
        audio_bytes = b"".join(result)

    output_file = create_output_file(OUTPUT_DIRECTORY, "voice_change",
                                        output_format_container)
    with output_file.open("wb") as f:
        f.write(audio_bytes)

    return GeneratedAudioResult(file_path=str(output_file))

@mcp.tool(description="""
        Create a new voice from an existing voice localized to a new language and dialect.

        Parameters
        ----------
        voice_id : str
            The ID of the voice to localize.

        name : str
            The name of the new localized voice.

        description : str
            The description of the new localized voice.

        language : SupportedLanguage

        original_speaker_gender : Gender

        dialect : typing.Optional[LocalizeDialectParams]

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.
        """)
def localize_voice(
    voice_id: str,
    name: str,
    description: str,
    language: SupportedLanguage,
    original_speaker_gender: Gender,
    dialect: typing.Optional[LocalizeDialectParams] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> VoiceMetadata:
    return client.voices.localize(
        voice_id=voice_id,
        name=name,
        description=description,
        language=language,
        original_speaker_gender=original_speaker_gender,
        dialect=dialect,
        request_options=request_options,
    )


@mcp.tool(description="""
        Parameters
        ----------
        voice_id : str
            The ID of the voice to delete.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.
        """)
def delete_voice(
    voice_id: str,
    request_options: typing.Optional[RequestOptions] = None
) -> DeleteVoiceResult:
    client.voices.delete(id=voice_id, request_options=request_options)
    return DeleteVoiceResult(success=True)

@mcp.tool(description="""
        Parameters
        ----------
        voice_id : str
            The ID of the voice to get.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.
        """)
def get_voice(
        voice_id: str,
        request_options: typing.Optional[RequestOptions] = None
) -> Voice:
    return client.voices.get(id=voice_id, request_options=request_options)


@mcp.tool(description="""
        Parameters
        ----------
        id : VoiceId

        name : str
            The name of the voice.

        description : str
            The description of the voice.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.
        """)
def update_voice(
        voice_id: str,
        name: str,
        description: str,
        request_options: typing.Optional[RequestOptions] = None
) -> Voice:
    return client.voices.update(
        id=voice_id,
        name=name,
        description=description,
        request_options=request_options,
    )

@mcp.tool(description="""
        Clone a voice from an audio clip. This endpoint has two modes, stability and similarity.

        Similarity mode clones are more similar to the source clip, but may reproduce background noise. For these, use an audio clip about 5 seconds long.

        Stability mode clones are more stable, but may not sound as similar to the source clip. For these, use an audio clip 10-20 seconds long.

        Parameters
        ----------
        file_path : str
            The absolute path to the audio file to clone.

        name : str
            The name of the voice.

        language : SupportedLanguage
            The language of the voice.

        mode : CloneMode
            Tradeoff between similarity and stability. Similarity clones sound more like the source clip, but may reproduce background noise. Stability clones always sound like a studio recording, but may not sound as similar to the source clip.

        description : typing.Optional[str]
            A description for the voice.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.
        """)
def clone_voice(
    file_path: str,
    name: str,
    language: SupportedLanguage,
    mode: CloneMode,
    description: typing.Optional[str] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> VoiceMetadata:
    with open(file_path, "rb") as clip:
        return client.voices.clone(
            clip=clip,
            name=name,
            language=language,
            mode=mode,
            description=description,
            request_options=request_options,
        )

@mcp.tool(description="""
        Parameters
        ----------
        limit : typing.Optional[int]
            The number of Voices to return per page, ranging between 1 and 100.

        starting_after : typing.Optional[str]
            A cursor to use in pagination. `starting_after` is a Voice ID that defines your
            place in the list. For example, if you make a /voices request and receive 100
            objects, ending with `voice_abc123`, your subsequent call can include
            `starting_after=voice_abc123` to fetch the next page of the list.

        ending_before : typing.Optional[str]
            A cursor to use in pagination. `ending_before` is a Voice ID that defines your
            place in the list. For example, if you make a /voices request and receive 100
            objects, starting with `voice_abc123`, your subsequent call can include
            `ending_before=voice_abc123` to fetch the previous page of the list.

        is_owner : typing.Optional[bool]
            Whether to only return voices owned by the current user.

        is_starred : typing.Optional[bool]
            Whether to only return starred voices.

        gender : typing.Optional[GenderPresentation]
            The gender presentation of the voices to return.

        language : typing.Optional[str]
            Filter voices by language or locale, such as `en`, `it`, or `en_GB`.
            A locale returns accents for that region; a language alone returns all accents
            for that language. Both `-` and `_` separators are accepted.

        q : typing.Optional[str]
            Search voices by name, description, or voice ID.

        expand : typing.Optional[typing.Sequence[str]]
            Additional fields to include in the response, such as `preview_file_url`.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration.
        """)
def list_voices(
    limit: typing.Optional[int] = 10,
    starting_after: typing.Optional[str] = None,
    ending_before: typing.Optional[str] = None,
    is_owner: typing.Optional[bool] = None,
    is_starred: typing.Optional[bool] = None,
    gender: typing.Optional[GenderPresentation] = None,
    language: typing.Optional[str] = None,
    q: typing.Optional[str] = None,
    expand: typing.Optional[typing.Sequence[str]] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> ListVoicesResult:
    merged_request_options = build_list_voices_request_options(
        request_options,
        language=language,
        q=q,
        expand=expand,
    )
    pager = client.voices.list(
        limit=limit,
        gender=gender,
        is_owner=is_owner,
        is_starred=is_starred,
        starting_after=starting_after,
        ending_before=ending_before,
        request_options=merged_request_options,
    )
    return voice_list_page_to_result(pager)


DEFAULT_STT_BATCH_MODEL = "ink-whisper"
DEFAULT_STT_STREAM_MODEL = "ink-2"
SttMode = typing.Literal["batch", "stream"]


def _resolve_stt_model(mode: SttMode, model: typing.Optional[str]) -> str:
    if model is not None:
        return model
    return DEFAULT_STT_BATCH_MODEL if mode == "batch" else DEFAULT_STT_STREAM_MODEL


def _speech_to_text_batch(
    *,
    file_path: str,
    model: str,
    language: typing.Optional[str],
    encoding: typing.Optional[SttEncoding],
    sample_rate: typing.Optional[int],
    timestamp_granularities: typing.Optional[typing.Sequence[TimestampGranularity]],
    request_options: typing.Optional[RequestOptions],
) -> TranscriptionResponse:
    with open(file_path, "rb") as audio_file:
        kwargs: dict[str, typing.Any] = {
            "file": audio_file,
            "model": model,
            "request_options": request_options,
        }
        if language is not None:
            kwargs["language"] = language
        if encoding is not None:
            kwargs["encoding"] = encoding
        if sample_rate is not None:
            kwargs["sample_rate"] = sample_rate
        if timestamp_granularities is not None:
            kwargs["timestamp_granularities"] = list(timestamp_granularities)
        return client.stt.transcribe(**kwargs)


def _speech_to_text_stream(
    *,
    file_path: str,
    model: str,
    language: typing.Optional[str],
    encoding: typing.Optional[SttEncoding],
    sample_rate: typing.Optional[int],
    timestamp_granularities: typing.Optional[typing.Sequence[TimestampGranularity]],
) -> TranscriptionResponse:
    stream_encoding, stream_sample_rate, chunks = iter_stt_audio_chunks(
        file_path,
        encoding=encoding,
        sample_rate=sample_rate,
    )
    stt_language = language if language is not None else "en"
    full_text = ""
    duration: typing.Optional[float] = None
    response_language: typing.Optional[str] = stt_language
    words: typing.Optional[typing.List[typing.Any]] = None

    for result in client.stt.websocket(
        model=model,
        language=stt_language,
        encoding=stream_encoding,
        sample_rate=stream_sample_rate,
    ).transcribe(
        chunks,
        model=model,
        language=stt_language,
        encoding=stream_encoding,
        sample_rate=stream_sample_rate,
    ):
        if result.get("type") != "transcript":
            continue
        if result.get("is_final"):
            full_text += result.get("text", "")
            if (
                timestamp_granularities
                and "word" in timestamp_granularities
                and "words" in result
            ):
                words = result["words"]
        if "duration" in result:
            duration = result["duration"]
        if "language" in result:
            response_language = result["language"]

    return TranscriptionResponse(
        text=full_text,
        language=response_language,
        duration=duration,
        words=words,
    )


@mcp.tool(description="""
        Transcribe a pre-recorded audio file to text.

        **Default (`mode="batch"`):** upload the file via batch STT (`POST /stt`).
        Best for typical MCP file-on-disk tasks (mp3, flac, wav, and other containers).
        Default model: `ink-whisper`.

        **Streaming (`mode="stream"`):** send mono PCM over STT WebSocket (`/stt/websocket`).
        Use for mono PCM WAV (for example TTS output) or raw PCM with `encoding` and
        `sample_rate`. Default model: `ink-2`.

        **Pricing:** See [STT pricing](https://docs.cartesia.ai/pricing#speech-to-text).

        Parameters
        ----------
        file_path : str
            Absolute path to the audio file.

        mode : str
            `batch` (default) or `stream`.

        model : typing.Optional[str]
            STT model ID. Defaults to `ink-whisper` for batch and `ink-2` for stream.

        language : typing.Optional[str]
            ISO-639-1 language code (defaults to `en` for stream; batch uses API default).

        encoding : typing.Optional[SttEncoding]
            Required for raw PCM without a container header (both modes).

        sample_rate : typing.Optional[int]
            Sample rate in Hz when `encoding` is set.

        timestamp_granularities : typing.Optional[typing.Sequence[TimestampGranularity]]
            Pass `["word"]` for word-level timestamps when supported.

        request_options : typing.Optional[RequestOptions]
            Request-specific configuration (batch mode only).
        """)
def speech_to_text(
    file_path: str,
    mode: SttMode = "batch",
    model: typing.Optional[str] = None,
    language: typing.Optional[str] = None,
    encoding: typing.Optional[SttEncoding] = None,
    sample_rate: typing.Optional[int] = None,
    timestamp_granularities: typing.Optional[typing.Sequence[TimestampGranularity]] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> TranscriptionResponse:
    stt_model = _resolve_stt_model(mode, model)
    if mode == "stream":
        _ = request_options
        return _speech_to_text_stream(
            file_path=file_path,
            model=stt_model,
            language=language,
            encoding=encoding,
            sample_rate=sample_rate,
            timestamp_granularities=timestamp_granularities,
        )
    return _speech_to_text_batch(
        file_path=file_path,
        model=stt_model,
        language=language,
        encoding=encoding,
        sample_rate=sample_rate,
        timestamp_granularities=timestamp_granularities,
        request_options=request_options,
    )


@mcp.tool(description="""
        Returns credit usage over time (`GET /usage/credits`).

        Requires **CARTESIA_ADMIN_API_KEY** (admin API keys cannot be used as CARTESIA_API_KEY).
        Optional `start_ts` and `end_ts` are RFC 3339 datetimes;
        `interval` buckets results by `day`, `week`, or `month`.

        Parameters
        ----------
        start_ts : typing.Optional[str]

        end_ts : typing.Optional[str]

        interval : typing.Optional[UsageInterval]

        api_key_id : typing.Optional[str]
            Limit usage to a specific API key ID.
        """)
def get_credit_usage(
    start_ts: typing.Optional[str] = None,
    end_ts: typing.Optional[str] = None,
    interval: typing.Optional[UsageInterval] = None,
    api_key_id: typing.Optional[str] = None,
) -> dict[str, typing.Any]:
    return extra_api.get_usage_credits(
        _require_admin_http(),
        start_ts=start_ts,
        end_ts=end_ts,
        interval=interval,
        api_key_id=api_key_id,
    )


@mcp.tool(description="""
        List pronunciation dictionaries for the authenticated user.

        Parameters
        ----------
        limit : typing.Optional[int]
            Number of dictionaries per page (1–100).

        starting_after : typing.Optional[str]
            Cursor: dictionary ID to start after.

        ending_before : typing.Optional[str]
            Cursor: dictionary ID to end before.
        """)
def list_pronunciation_dicts(
    limit: typing.Optional[int] = 10,
    starting_after: typing.Optional[str] = None,
    ending_before: typing.Optional[str] = None,
) -> ListPronunciationDictsResult:
    payload = extra_api.list_pronunciation_dicts(
        http,
        limit=limit,
        starting_after=starting_after,
        ending_before=ending_before,
    )
    return pronunciation_dict_list_to_result(payload)


@mcp.tool(description="""
        Create a pronunciation dictionary.

        Parameters
        ----------
        name : str

        items : typing.Optional[typing.Sequence[PronunciationDictItemParams]]
            Mappings of `text` to `pronunciation` (IPA or sounds-like).
        """)
def create_pronunciation_dict(
    name: str,
    items: typing.Optional[typing.Sequence[PronunciationDictItemParams]] = None,
) -> dict[str, typing.Any]:
    return extra_api.create_pronunciation_dict(http, name=name, items=items)


@mcp.tool(description="""
        Parameters
        ----------
        dict_id : str
            Pronunciation dictionary ID.
        """)
def get_pronunciation_dict(dict_id: str) -> dict[str, typing.Any]:
    return extra_api.get_pronunciation_dict(http, dict_id)


@mcp.tool(description="""
        Update a pronunciation dictionary.

        Parameters
        ----------
        dict_id : str

        name : typing.Optional[str]

        items : typing.Optional[typing.Sequence[PronunciationDictItemParams]]
        """)
def update_pronunciation_dict(
    dict_id: str,
    name: typing.Optional[str] = None,
    items: typing.Optional[typing.Sequence[PronunciationDictItemParams]] = None,
) -> dict[str, typing.Any]:
    return extra_api.update_pronunciation_dict(http, dict_id, name=name, items=items)


@mcp.tool(description="""
        Parameters
        ----------
        dict_id : str
            Pronunciation dictionary ID to delete.
        """)
def delete_pronunciation_dict(dict_id: str) -> DeletePronunciationDictResult:
    extra_api.delete_pronunciation_dict(http, dict_id)
    return DeletePronunciationDictResult(success=True)


def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
