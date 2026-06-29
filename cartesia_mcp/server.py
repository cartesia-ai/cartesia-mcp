"""
Cartesia MCP Server
"""

import os
import typing
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from cartesia import Cartesia, RequestOptions, omit
from cartesia.types import (
    GenderPresentation,
    GenerationConfigParam,
    OutputFormatContainer,
    RawEncoding,
    STTEncoding,
    STTTranscribeResponse,
    SupportedLanguage,
    Voice,
    VoiceMetadata,
)
from cartesia.types.shared.word_timestamps import WordTimestamps
from cartesia.types.stt_transcribe_response import Word as SttWord
from cartesia.types.tts_generate_params import OutputFormat
from cartesia.types.voice_specifier_param import VoiceSpecifierParam

from cartesia_mcp.custom_types import (
    DeletePronunciationDictResult,
    DeleteVoiceResult,
    GeneratedAudioResult,
    ListPronunciationDictsResult,
    ListVoicesResult,
    PronunciationDictItemParams,
)
from cartesia_mcp.constants import DEFAULT_MODEL_ID
from cartesia_mcp import extra_api
from cartesia_mcp.extra_api import UsageInterval
from cartesia_mcp.config import ensure_admin_client, env_or_none, validate_api_keys
from cartesia_mcp.request_options import sdk_kwargs_from_request_options
from cartesia_mcp.sdk_setup import create_cartesia_client
from cartesia_mcp.utils import (
    create_output_file,
    cursor_page_to_result,
    iter_stt_audio_chunks,
    voice_list_page_to_result,
)

load_dotenv()

CARTESIA_API_KEY, CARTESIA_ADMIN_API_KEY = validate_api_keys(
    env_or_none("CARTESIA_API_KEY"),
    env_or_none("CARTESIA_ADMIN_API_KEY"),
)

OUTPUT_DIRECTORY = os.getenv("OUTPUT_DIRECTORY", ".")

client = create_cartesia_client(CARTESIA_API_KEY)
admin_client = (
    create_cartesia_client(CARTESIA_ADMIN_API_KEY)
    if CARTESIA_ADMIN_API_KEY
    else None
)
mcp = FastMCP("Cartesia")


def _require_admin_client() -> Cartesia:
    return ensure_admin_client(admin_client)


def _build_generation_config(
    *,
    speed: typing.Optional[float] = None,
    volume: typing.Optional[float] = None,
    emotion: typing.Optional[str] = None,
) -> typing.Optional[GenerationConfigParam]:
    if speed is None and volume is None and emotion is None:
        return None
    config: GenerationConfigParam = {}
    if speed is not None:
        config["speed"] = speed
    if volume is not None:
        config["volume"] = volume
    if emotion is not None:
        config["emotion"] = emotion
    return config


def _merge_extra_body(
    sdk_kwargs: dict[str, typing.Any],
    extra_fields: dict[str, typing.Any],
) -> None:
    if not extra_fields:
        return
    existing = sdk_kwargs.get("extra_body")
    if isinstance(existing, dict):
        sdk_kwargs["extra_body"] = {**existing, **extra_fields}
    else:
        sdk_kwargs["extra_body"] = extra_fields


def _stt_words_from_timestamps(
    word_timestamp_groups: typing.Optional[typing.Sequence[WordTimestamps]],
) -> typing.Optional[typing.List[SttWord]]:
    if not word_timestamp_groups:
        return None
    words: list[SttWord] = []
    for group in word_timestamp_groups:
        for word, start, end in zip(group.words, group.start, group.end):
            words.append(SttWord(word=word, start=start, end=end))
    return words or None


def _wants_word_timestamps(
    timestamp_granularities: typing.Optional[typing.Sequence[typing.Literal["word"]]],
) -> bool:
    return bool(timestamp_granularities and "word" in timestamp_granularities)


def _stream_stt_uses_manual_finalize(
    *,
    language: typing.Optional[str],
    timestamp_granularities: typing.Optional[typing.Sequence[typing.Literal["word"]]],
) -> bool:
    if _wants_word_timestamps(timestamp_granularities):
        return True
    return language is not None and language != "en"


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
    voice: VoiceSpecifierParam,
    output_format: OutputFormat,
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
        "pronunciation_dict_id": pronunciation_dict_id,
        **sdk_kwargs_from_request_options(request_options),
    }
    if generation_config is not None:
        tts_kwargs["generation_config"] = generation_config
    if duration is not None:
        _merge_extra_body(tts_kwargs, {"duration": duration})
    result = client.tts.generate(**tts_kwargs)

    output_file = create_output_file(OUTPUT_DIRECTORY, "text_to_speech",
                                        output_format["container"])

    audio_bytes = result.read()
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
        result = client.voice_changer.generate(
            clip=clip,
            voice_id=voice_id,
            output_format_container=output_format_container,
            output_format_sample_rate=output_format_sample_rate,
            output_format_encoding=output_format_encoding,
            output_format_bit_rate=output_format_bit_rate,
            **sdk_kwargs_from_request_options(request_options),
        )
        audio_bytes = result.read()

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
    original_speaker_gender: typing.Literal["male", "female"],
    dialect: typing.Optional[str] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> VoiceMetadata:
    return client.voices.localize(
        voice_id=voice_id,
        name=name,
        description=description,
        language=language,
        original_speaker_gender=original_speaker_gender,
        dialect=dialect,
        **sdk_kwargs_from_request_options(request_options),
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
    client.voices.delete(id=voice_id, **sdk_kwargs_from_request_options(request_options))
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
    return client.voices.get(id=voice_id, **sdk_kwargs_from_request_options(request_options))


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
        **sdk_kwargs_from_request_options(request_options),
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
    mode: str,
    description: typing.Optional[str] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> VoiceMetadata:
    clone_kwargs = sdk_kwargs_from_request_options(request_options)
    _merge_extra_body(clone_kwargs, {"mode": mode})
    with open(file_path, "rb") as clip:
        return client.voices.clone(
            clip=clip,
            name=name,
            language=language,
            description=description,
            **clone_kwargs,
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
    extra_query: dict[str, typing.Any] = {}
    if language is not None:
        extra_query["language"] = language
    pager = client.voices.list(
        limit=limit,
        gender=gender,
        is_owner=is_owner,
        is_starred=is_starred,
        starting_after=starting_after,
        ending_before=ending_before,
        q=q,
        expand=list(expand) if expand else omit,
        **sdk_kwargs_from_request_options(request_options, extra_query=extra_query),
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
    encoding: typing.Optional[STTEncoding],
    sample_rate: typing.Optional[int],
    timestamp_granularities: typing.Optional[typing.Sequence[typing.Literal["word"]]],
    request_options: typing.Optional[RequestOptions],
) -> STTTranscribeResponse:
    with open(file_path, "rb") as audio_file:
        kwargs: dict[str, typing.Any] = {
            "file": audio_file,
            "model": model,
            **sdk_kwargs_from_request_options(request_options),
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


def _speech_to_text_stream_auto_finalize(
    *,
    model: str,
    stream_encoding: STTEncoding,
    stream_sample_rate: int,
    chunks: typing.Iterable[bytes],
    response_language: typing.Optional[str],
) -> STTTranscribeResponse:
    full_text = ""

    with client.stt.auto_finalize.websocket(
        model=model,
        encoding=stream_encoding,
        sample_rate=stream_sample_rate,
    ) as connection:
        for chunk in chunks:
            connection.send_raw(chunk)

        connection.send({"type": "close"})

        for event in connection:
            if event.type == "turn.end":
                full_text += event.transcript
            elif event.type == "error":
                raise RuntimeError(f"STT stream error: {event}")

    return STTTranscribeResponse(
        text=full_text,
        type="transcript",
        language=response_language,
    )


def _speech_to_text_stream_manual_finalize(
    *,
    model: str,
    stream_encoding: STTEncoding,
    stream_sample_rate: int,
    chunks: typing.Iterable[bytes],
    language: typing.Optional[str],
    timestamp_granularities: typing.Optional[typing.Sequence[typing.Literal["word"]]],
) -> STTTranscribeResponse:
    stt_language = language if language is not None else "en"
    extra_query: dict[str, typing.Any] = {}
    if language is not None and language != "en":
        extra_query["language"] = language
    if _wants_word_timestamps(timestamp_granularities):
        extra_query["timestamp_granularities[]"] = "word"

    websocket_kwargs: dict[str, typing.Any] = {
        "model": model,
        "encoding": stream_encoding,
        "sample_rate": stream_sample_rate,
    }
    if stt_language == "en":
        websocket_kwargs["language"] = "en"
    if extra_query:
        websocket_kwargs["extra_query"] = extra_query

    full_text = ""
    duration: typing.Optional[float] = None
    response_language: typing.Optional[str] = stt_language
    words: typing.Optional[typing.List[SttWord]] = None

    with client.stt.manual_finalize.websocket(**websocket_kwargs) as connection:
        for chunk in chunks:
            connection.send_raw(chunk)

        connection.send("finalize")
        connection.send("close")

        for event in connection:
            if event.type == "transcript":
                if event.is_final:
                    full_text += event.text
                    if _wants_word_timestamps(timestamp_granularities) and event.words:
                        words = _stt_words_from_timestamps(event.words)
                if event.duration is not None:
                    duration = event.duration
                if event.language is not None:
                    response_language = event.language
            elif event.type == "error":
                raise RuntimeError(f"STT stream error: {event}")

    return STTTranscribeResponse(
        text=full_text,
        type="transcript",
        language=response_language,
        duration=duration,
        words=words,
    )


def _speech_to_text_stream(
    *,
    file_path: str,
    model: str,
    language: typing.Optional[str],
    encoding: typing.Optional[STTEncoding],
    sample_rate: typing.Optional[int],
    timestamp_granularities: typing.Optional[typing.Sequence[typing.Literal["word"]]],
) -> STTTranscribeResponse:
    stream_encoding, stream_sample_rate, chunks = iter_stt_audio_chunks(
        file_path,
        encoding=encoding,
        sample_rate=sample_rate,
    )
    stt_language = language if language is not None else "en"

    if _stream_stt_uses_manual_finalize(
        language=language,
        timestamp_granularities=timestamp_granularities,
    ):
        return _speech_to_text_stream_manual_finalize(
            model=model,
            stream_encoding=stream_encoding,
            stream_sample_rate=stream_sample_rate,
            chunks=chunks,
            language=language,
            timestamp_granularities=timestamp_granularities,
        )

    return _speech_to_text_stream_auto_finalize(
        model=model,
        stream_encoding=stream_encoding,
        stream_sample_rate=stream_sample_rate,
        chunks=chunks,
        response_language=stt_language,
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
    encoding: typing.Optional[STTEncoding] = None,
    sample_rate: typing.Optional[int] = None,
    timestamp_granularities: typing.Optional[typing.Sequence[typing.Literal["word"]]] = None,
    request_options: typing.Optional[RequestOptions] = None,
) -> STTTranscribeResponse:
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
        _require_admin_client(),
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
    page = client.pronunciation_dicts.list(
        limit=limit,
        starting_after=starting_after,
        ending_before=ending_before,
    )
    return typing.cast(ListPronunciationDictsResult, cursor_page_to_result(page))


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
    return client.pronunciation_dicts.create(
        name=name,
        items=list(items) if items is not None else omit,
    ).model_dump(mode="json")


@mcp.tool(description="""
        Parameters
        ----------
        dict_id : str
            Pronunciation dictionary ID.
        """)
def get_pronunciation_dict(dict_id: str) -> dict[str, typing.Any]:
    return client.pronunciation_dicts.retrieve(dict_id).model_dump(mode="json")


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
    if name is None and items is None:
        raise ValueError("At least one of `name` or `items` must be provided.")
    kwargs: dict[str, typing.Any] = {}
    if name is not None:
        kwargs["name"] = name
    if items is not None:
        kwargs["items"] = list(items)
    return client.pronunciation_dicts.update(dict_id, **kwargs).model_dump(mode="json")


@mcp.tool(description="""
        Parameters
        ----------
        dict_id : str
            Pronunciation dictionary ID to delete.
        """)
def delete_pronunciation_dict(dict_id: str) -> DeletePronunciationDictResult:
    client.pronunciation_dicts.delete(dict_id)
    return DeletePronunciationDictResult(success=True)


def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
