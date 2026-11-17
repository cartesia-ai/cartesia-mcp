"""
Cartesia MCP Server
"""

import argparse
import os
import sys
import typing
from pathlib import Path

from cartesia import Cartesia, omit
from cartesia.types import (
    AttachVoiceAccent,
    Gender,
    GenderPresentation,
    GenerationConfigParam,
    ListAccentsResponse,
    LocalizeDialect,
    LocalizeTargetLanguage,
    OutputFormatContainer,
    STTEncoding,
    STTTranscribeResponse,
    SupportedLanguage,
    Voice,
    VoiceAccent,
    VoiceMetadata,
)
from cartesia.types.agent_create_params import Config as AgentCreateConfig
from cartesia.types.agent_update_params import Config as AgentUpdateConfig
from cartesia.types.agents.call_create_params import OutboundCall
from cartesia.types.agents.knowledge_base.document_create_bulk_params import (
    Document as KnowledgeDocumentInput,
)
from cartesia.types.agents.phone_number_import_params import Provider as ImportProvider
from cartesia.types.agents.phone_numbers.provider_update_params import (
    ProviderUpdateParams,
)
from cartesia.types.agents.tool_create_params import ToolCreateParams
from cartesia.types.agents.tool_update_params import ToolUpdateParams
from cartesia.types.shared.word_timestamps import WordTimestamps
from cartesia.types.stt_transcribe_response import Word as SttWord
from cartesia.types.tts_generate_params import OutputFormat
from dotenv import load_dotenv
from mcp.types import ToolAnnotations
from pydantic import Field

from cartesia_mcp import __version__, extra_api
from cartesia_mcp.branding import (
    SERVER_DESCRIPTION,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    WEBSITE_URL,
    playground_agent_url,
    server_icons,
)
from cartesia_mcp.clients import client, require_admin_client
from cartesia_mcp.config import env_or_none, validate_api_keys
from cartesia_mcp.constants import DEFAULT_MODEL_ID
from cartesia_mcp.credentials import configure_hosted_mode, configure_stdio_credentials
from cartesia_mcp.custom_types import (
    DeletePronunciationDictResult,
    DeleteVoiceResult,
    DownloadedFileResult,
    GeneratedAudioResult,
    ListPronunciationDictsResult,
    ListVoicesResult,
    PronunciationDictItemParams,
)
from cartesia_mcp.extra_api import (
    DownloadFormat,
    ModelCapability,
    UsageCreditsGroupBy,
    UsageInterval,
)
from cartesia_mcp.hosted import (
    configure_hosted_oauth_store,
    hosted_enabled,
    hosted_server_kwargs,
    run_hosted,
    server_public_url,
)
from cartesia_mcp.mcpserver import CartesiaMCP
from cartesia_mcp.utils import (
    agent_call_list_to_result,
    agent_version_list_to_result,
    coerce_null_voice_locales,
    condense_agent_call,
    create_output_file,
    cursor_page_to_result,
    default_output_directory,
    iter_stt_audio_chunks,
    list_response_to_result,
    page_result,
    resolve_local_download_filename,
    save_downloaded_file,
    sdk_page_to_result,
    start_output_directory_cleanup,
    voice_list_page_to_result,
)

load_dotenv()

_is_hosted = hosted_enabled() or (
    "--transport" in sys.argv and "streamable-http" in sys.argv
)
CARTESIA_API_KEY, CARTESIA_ADMIN_API_KEY = validate_api_keys(
    env_or_none("CARTESIA_API_KEY"),
    env_or_none("CARTESIA_ADMIN_API_KEY"),
    require_api_key=not _is_hosted,
)

OUTPUT_DIRECTORY = default_output_directory(hosted=_is_hosted)

if _is_hosted:
    configure_hosted_mode()
    if hosted_enabled():
        configure_hosted_oauth_store()
elif CARTESIA_API_KEY:
    configure_stdio_credentials(CARTESIA_API_KEY, CARTESIA_ADMIN_API_KEY)

mcp = CartesiaMCP(
    SERVER_NAME,
    description=SERVER_DESCRIPTION,
    instructions=SERVER_INSTRUCTIONS,
    website_url=WEBSITE_URL,
    icons=server_icons(origin=server_public_url() if _is_hosted else None),
    version=__version__,
    **(hosted_server_kwargs() if _is_hosted else {}),
)

# Tools only touch the caller's Cartesia account, so they are not open-world, except the
# few that reach a real phone network or spend money (`_real_world_tool`).
def _read_only_tool(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title, read_only_hint=True, idempotent_hint=True, open_world_hint=False
    )


def _additive_tool(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title, read_only_hint=False, destructive_hint=False, open_world_hint=False
    )


def _real_world_tool(title: str) -> ToolAnnotations:
    """Dials real phone numbers or buys one. Not undoable, so clients should ask first."""
    return ToolAnnotations(
        title=title, read_only_hint=False, destructive_hint=False, open_world_hint=True
    )


def _destructive_tool(title: str, *, idempotent: bool = True) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=idempotent,
        open_world_hint=False,
    )


def _require_admin_client() -> Cartesia:
    return require_admin_client()


def _api_client() -> Cartesia:
    return typing.cast(Cartesia, client)


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


def _resolve_tts_output_dest(
    output_path: typing.Optional[str],
    extension: OutputFormatContainer,
) -> typing.Optional[Path]:
    """Validate optional ``output_path`` before TTS. None means use ``OUTPUT_DIRECTORY``."""
    path = output_path.strip() if isinstance(output_path, str) else ""
    if not path:
        return None
    if _is_hosted:
        raise ValueError(
            "output_path is only supported with the local Cartesia MCP server "
            "(stdio / uvx). On hosted MCP (mcp.cartesia.ai), omit output_path and "
            "use file_id / download_url, or run the local server to write into "
            "your project."
        )
    dest = Path(path).expanduser()
    if not dest.is_absolute():
        dest = Path.cwd() / dest
    dest = dest.resolve()
    if dest.exists() and dest.is_dir():
        raise ValueError(
            f"output_path '{path}' is a directory; pass a file path "
            f"(for example '{dest / f'audio.{extension}'}')."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(dest.parent, os.W_OK):
        raise ValueError(f"Cannot write to directory {dest.parent}")
    return dest


def _write_audio_output(
    audio_bytes: bytes,
    tool_type: typing.Literal["text_to_speech"],
    extension: OutputFormatContainer,
    *,
    dest: typing.Optional[Path] = None,
) -> str:
    if dest is not None:
        dest.write_bytes(audio_bytes)
        return str(dest)

    output_file = create_output_file(OUTPUT_DIRECTORY, tool_type, extension)
    with output_file.open("wb") as f:
        f.write(audio_bytes)
    return str(output_file)


def _try_create_download_link(
    file_id: str,
    *,
    format: typing.Optional[DownloadFormat] = None,
) -> typing.Optional[str]:
    """Mint a time-limited public download link; None if POST /links fails."""
    try:
        link_url = extra_api.create_file_download_link(
            _api_client(), file_id
        )
        return extra_api.with_download_format(link_url, format)
    except Exception:
        return None


def _cloud_file_on_disk(
    file_id: str,
    *,
    format: typing.Optional[DownloadFormat] = None,
) -> tuple[Path, str]:
    """Download a cloud file onto this MCP server. Returns ``(path, filename)``."""
    sdk_client = _api_client()
    metadata = extra_api.get_file_info(sdk_client, file_id)
    filename = metadata.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        filename = file_id

    local_filename = resolve_local_download_filename(
        filename,
        file_id,
        as_wav=format == "playback",
    )
    content = extra_api.download_file_bytes(sdk_client, file_id, format=format)
    output_path = save_downloaded_file(
        OUTPUT_DIRECTORY,
        file_id=file_id,
        filename=local_filename,
        content=content,
    )
    return output_path, local_filename


def _is_hosted_output_file(path: Path) -> bool:
    """Hosted ``file_path`` inputs must be files this server wrote under ``OUTPUT_DIRECTORY``."""
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return resolved.is_file() and resolved.is_relative_to(
        Path(OUTPUT_DIRECTORY).resolve()
    )


def _resolve_audio_input(
    file_path: typing.Optional[str],
    file_id: typing.Optional[str],
) -> str:
    """Resolve ``file_id`` (cloud) or ``file_path`` (this machine) to a local path."""
    path = file_path.strip() if isinstance(file_path, str) else ""
    cloud_id = file_id.strip() if isinstance(file_id, str) else ""
    if path and cloud_id:
        raise ValueError("Pass file_id or file_path, not both.")
    if cloud_id:
        output_path, _filename = _cloud_file_on_disk(cloud_id)
        return str(output_path)
    if path:
        resolved = Path(path).expanduser()
        if _is_hosted and not _is_hosted_output_file(resolved):
            raise ValueError(
                f"Path '{path}' was not found on the MCP server. When using the "
                "hosted Cartesia MCP server (mcp.cartesia.ai), pass file_id from "
                "text_to_speech or download_file — a path on your computer is not "
                "visible to this server."
            )
        if not resolved.exists():
            raise ValueError(
                f"Local file '{path}' does not exist on this MCP server."
            )
        if not resolved.is_file():
            raise ValueError(f"'{path}' is not a file.")
        return str(resolved.resolve())
    raise ValueError(
        "Pass file_id (a Cartesia cloud file) or file_path "
        "(an absolute path on this MCP server)."
    )


def _deliver_cloud_file(
    file_id: str,
    *,
    format: typing.Optional[DownloadFormat] = None,
) -> DownloadedFileResult:
    output_path, local_filename = _cloud_file_on_disk(file_id, format=format)
    delivered: DownloadedFileResult = {
        "file_id": file_id,
        "file_path": str(output_path),
        "filename": local_filename,
    }
    download_url = _try_create_download_link(file_id, format=format)
    if download_url is not None:
        delivered["download_url"] = download_url
    return delivered


@mcp.tool(
    annotations=_additive_tool("Convert text to speech"),
    description="""
        Generate speech audio from text. By default (`save=true`) the audio is persisted
        in Cartesia cloud storage and the response includes `file_id` and `download_url`
        (24-hour public link). Pass that `file_id` to `speech_to_text` or `clone_voice`
        — including from a hosted client whose disk is not this server.
        `download_url` is a browser link. On the local server, `file_path` is a copy under
        `OUTPUT_DIRECTORY` (or `output_path`). On hosted MCP with `save=true` (the default),
        `file_path` is omitted — use `file_id` / `download_url` instead.
        """)
def text_to_speech(
    transcript: typing.Annotated[
        str,
        Field(description="Text to synthesize."),
    ],
    voice_id: typing.Annotated[
        str,
        Field(description="Cartesia voice ID (e.g. from `list_voices`)."),
    ],
    output_format: typing.Annotated[
        OutputFormat,
        Field(description="Audio output format: `container` (`wav`, `mp3`, or `raw`), `encoding`, and `sample_rate`."),
    ],
    model_id: typing.Annotated[
        typing.Optional[str],
        Field(description="The ID of the model to use for the generation. Call `list_models` with `capability=\"tts\"` for valid ids."),
    ] = DEFAULT_MODEL_ID,
    language: typing.Annotated[
        typing.Optional[SupportedLanguage],
        Field(description="Language of the transcript as an ISO 639-1 code (e.g. `en`, `es`)."),
    ] = None,
    duration: typing.Annotated[
        typing.Optional[float],
        Field(description="The maximum duration of the audio in seconds. You do not usually need to specify this. If the duration is not appropriate for the length of the transcript, the output audio may be truncated."),
    ] = None,
    speed: typing.Annotated[
        typing.Optional[float],
        Field(description="Speech speed multiplier (0.6–1.5). Applies to Sonic 3+ via `generation_config`."),
    ] = None,
    volume: typing.Annotated[
        typing.Optional[float],
        Field(description="Volume multiplier (0.5–2.0). Applies to Sonic 3+ via `generation_config`."),
    ] = None,
    emotion: typing.Annotated[
        typing.Optional[str],
        Field(description="Emotional guidance for the generation (e.g. `neutral`, `excited`, `sad`). Applies to Sonic 3+."),
    ] = None,
    pronunciation_dict_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Pronunciation dictionary ID to apply for this generation only."),
    ] = None,
    output_path: typing.Annotated[
        typing.Optional[str],
        Field(description="Local file path to write the audio (for example `src/assets/audio/click.wav`). Relative paths resolve against the MCP server working directory. Only supported with the local server (stdio / uvx); rejected on hosted MCP."),
    ] = None,
    save: typing.Annotated[
        bool,
        Field(description="When true (default), persist the generation to cloud storage and return `file_id` plus `download_url`. Pass `download_file` with that `file_id` to refresh the link or write another local copy."),
    ] = True,
) -> GeneratedAudioResult:
    dest = _resolve_tts_output_dest(output_path, output_format["container"])
    generation_config = _build_generation_config(
        speed=speed,
        volume=volume,
        emotion=emotion,
    )
    tts_kwargs: dict[str, typing.Any] = {
        "transcript": transcript,
        "voice": voice_id,
        "output_format": output_format,
        "model_id": model_id,
        "language": language,
        "pronunciation_dict_id": pronunciation_dict_id,
    }
    if generation_config is not None:
        tts_kwargs["generation_config"] = generation_config
    if duration is not None:
        _merge_extra_body(tts_kwargs, {"duration": duration})
    tts_kwargs["save"] = save
    result = _api_client().tts.generate(**tts_kwargs)

    audio_bytes = result.read()
    # Hosted + cloud save: skip the local copy. Clients use file_id / download_url;
    # writing every generation under OUTPUT_DIRECTORY filled Render ephemeral disk.
    write_local = dest is not None or not save or not _is_hosted
    file_path = (
        _write_audio_output(
            audio_bytes,
            "text_to_speech",
            output_format["container"],
            dest=dest,
        )
        if write_local
        else None
    )

    if not save:
        return GeneratedAudioResult(file_path=file_path)

    file_id = extra_api.file_id_from_response_headers(result.headers)
    if not file_id:
        raise RuntimeError(
            "TTS save was requested but the API did not return Cartesia-File-ID",
        )

    saved: GeneratedAudioResult = {
        "file_id": file_id,
    }
    if file_path is not None:
        saved["file_path"] = file_path
    download_url = _try_create_download_link(file_id)
    if download_url is not None:
        saved["download_url"] = download_url
    return saved


@mcp.tool(
    annotations=_additive_tool("Localize voice"),
    description="""
        Create a new voice from an existing voice localized to a new language and dialect.
        """)
def localize_voice(
    voice_id: typing.Annotated[
        str,
        Field(description="The ID of the voice to localize."),
    ],
    name: typing.Annotated[
        str,
        Field(description="The name of the new localized voice."),
    ],
    description: typing.Annotated[
        str,
        Field(description="The description of the new localized voice."),
    ],
    accent: typing.Annotated[
        VoiceAccent,
        Field(description="Catalog accent id from GET /accents (for example `mexican` or `parisian`). Display names are rejected on this API version."),
    ],
    language: typing.Annotated[
        LocalizeTargetLanguage,
        Field(description="Target language to localize the voice to. Distinct from TTS SupportedLanguage."),
    ],
    original_speaker_gender: typing.Annotated[
        Gender,
        Field(description="Gender of the speaker in the source voice."),
    ],
    dialect: typing.Annotated[
        typing.Optional[LocalizeDialect],
        Field(description="Dialect allowlist for English, Spanish, Portuguese, and French."),
    ] = None,
) -> VoiceMetadata:
    return _api_client().voices.localize(
        voice_id=voice_id,
        name=name,
        description=description,
        accent=accent,
        language=language,
        original_speaker_gender=original_speaker_gender,
        dialect=dialect,
    )


@mcp.tool(
    annotations=_destructive_tool("Delete voice"),
    description="""
        Permanently delete a voice you own.
        """)
def delete_voice(
    voice_id: typing.Annotated[
        str,
        Field(description="The ID of the voice to delete."),
    ],
) -> DeleteVoiceResult:
    _api_client().voices.delete(
        id=voice_id
    )
    return DeleteVoiceResult(success=True)

@mcp.tool(
    annotations=_read_only_tool("Get voice"),
    description="""
        Get a voice by ID.
        """)
def get_voice(
    voice_id: typing.Annotated[
        str,
        Field(description="The ID of the voice to get."),
    ],
) -> Voice:
    voice = _api_client().voices.get(
        id=voice_id
    )
    return coerce_null_voice_locales(voice)


@mcp.tool(
    annotations=_destructive_tool("Update voice"),
    description="""
        Update a voice's name and description.
        """)
def update_voice(
    voice_id: typing.Annotated[
        str,
        Field(description="The ID of the voice to update."),
    ],
    name: typing.Annotated[
        str,
        Field(description="The name of the voice."),
    ],
    description: typing.Annotated[
        str,
        Field(description="The description of the voice."),
    ],
) -> Voice:
    voice = _api_client().voices.update(
        id=voice_id,
        name=name,
        description=description,
    )
    return coerce_null_voice_locales(voice)


@mcp.tool(
    annotations=_read_only_tool("List accents"),
    description="""
        List the official accent catalog from GET /accents.
        
        Each entry includes the canonical accent `id` plus display metadata
        (`name`, `language`, `locale`, `is_locale_default`, `is_localizable`).
        Pass `id` to `clone_voice`, `add_voice_accents`, `delete_voice_accent`,
        and `localize_voice`. Display names are rejected on this API version.
        """)
def list_accents() -> ListAccentsResponse:
    return _api_client().voices.list_accents(
    )


@mcp.tool(
    annotations=_read_only_tool("List models"),
    description="""
        List callable Sonic (TTS) and Ink (STT) model ids from GET /models.

        These ids are for `text_to_speech` and `speech_to_text` only. Do not
        pass them as a Managed Agent `model.id`. Call `list_agent_models` for
        that catalog.

        Each row has `id` and `capability` (`tts` or `stt`). TTS rows include
        `supported_languages`, the sorted synthesis language codes that model accepts.
        STT rows include `modes` (`stream` and/or `batch`). Pass `id` to `text_to_speech` as
        `model_id` or to `speech_to_text` as `model`. Omit model on those tools
        when you want the API default. Preview ids (`sonic-preview`, `ink-preview`)
        are included when callable.
        """)
def list_models(
    capability: typing.Annotated[
        typing.Optional[ModelCapability],
        Field(description="Filter to TTS or STT. Omit to return both."),
    ] = None,
) -> dict[str, typing.Any]:
    return extra_api.list_models(
        _api_client(),
        capability=capability,
    )


@mcp.tool(
    annotations=_read_only_tool("List agent models"),
    description="""
        List LLMs available for Managed Agents from GET /v1/agents/models.

        Use these `id` values for an agent's `model.id` (and explicit fallback
        model ids). Do not invent model ids, and do not use ids from
        `list_models` (`sonic-*`, `ink-*`). Those are speech models. Each row
        includes provider, display name, latency, and token pricing. Returns
        the full catalog (pagination is followed server-side).
        """)
def list_agent_models() -> dict[str, typing.Any]:
    return extra_api.list_agent_models(
        _api_client(),
    )


AgentCallDetail = typing.Literal["condensed", "full"]
PhoneNumberProviderType = typing.Literal["twilio", "cartesia", "sip_trunk"]


def _or_omit(value: typing.Any) -> typing.Any:
    return omit if value is None else value


def _agent_with_playground_url(agent: typing.Any) -> dict[str, typing.Any]:
    result = agent.to_dict(mode="json")
    result["playground_url"] = playground_agent_url(result["id"])
    return result


@mcp.tool(
    annotations=_read_only_tool("List agents"),
    description="""
        List the account's Managed Agents, newest first.

        Rows have `id`, `name`, `description`, `version_id` (the current
        config version), and timestamps. Call `get_agent` for the config.
        """)
def list_agents(
    q: typing.Annotated[
        typing.Optional[str],
        Field(description="Search agents by name."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Agents per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: agent ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return sdk_page_to_result(
        _api_client().agents.list(
            q=_or_omit(q),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent"),
    description="""
        Get a Managed Agent: name, description, the current `config`
        (instructions, initial message, model, voice, tools, system tools,
        turn-taking, variables), the current `version`, and `playground_url`
        for trying the agent in the browser.
        """)
def get_agent(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
) -> dict[str, typing.Any]:
    return _agent_with_playground_url(_api_client().agents.retrieve(agent_id))


@mcp.tool(
    annotations=_additive_tool("Create agent"),
    description="""
        Create a Managed Agent: a hosted voice agent Cartesia runs for web,
        phone, and websocket calls.

        Write `config.instructions` for what the user described (role, goal,
        tone, steps, what to collect, when to end or transfer). An agent with
        no instructions runs a generic default prompt.

        - `config.model.id`: an id from `list_agent_models`.
        - `config.audio.output.voice_id`: a voice from `list_voices`.
        - `config.initial_message`: what the agent says first, or null to wait.
        - Per-caller context: reference `{{name}}` in instructions or the
          initial message, pass values when the call starts, and put sample
          values in `config.dynamic_variable_placeholders` for test calls.
        - Ending, transferring, DTMF, and voicemail detection are built in:
          enable them under `config.system_tools`. There are no separate
          transfer or end-call endpoints.
        - `config.tools` takes ids from `create_agent_tool` or `list_agent_tools`.
        - `config.knowledge_base_folders` and `config.knowledge_base_documents`
          take ids from `list_knowledge_folders` and `list_knowledge_documents`.
        - `config.event_webhook_id` takes an id from `list_event_webhooks`.

        There is no API to simulate a call. Open the returned `playground_url`
        to talk to the agent.
        """)
def create_agent(
    name: typing.Annotated[
        str,
        Field(min_length=1, description="Agent name. It does not need to be unique."),
    ],
    description: typing.Annotated[
        typing.Optional[str],
        Field(description="Short description of what the agent does."),
    ] = None,
    config: typing.Annotated[
        typing.Optional[AgentCreateConfig],
        Field(description="Agent config. Omitted fields use the API defaults."),
    ] = None,
) -> dict[str, typing.Any]:
    return _agent_with_playground_url(
        _api_client().agents.create(
            name=name,
            description=_or_omit(description),
            config=_or_omit(config),
        )
    )


@mcp.tool(
    annotations=_destructive_tool("Update agent"),
    description="""
        Update a Managed Agent. Send only the fields to change.

        Inside `config`, list and map fields (`tools`, `keyterms`,
        `knowledge_base_documents`, `dynamic_variable_placeholders`, ...)
        replace the existing value, so send the full list. Call `get_agent`
        first when editing one.

        Each `config` change publishes a new version, which live calls use
        right away. Describe it with `version_description`. Name and
        description changes do not create a version.
        """)
def update_agent(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    name: typing.Annotated[
        typing.Optional[str],
        Field(min_length=1, description="New agent name."),
    ] = None,
    description: typing.Annotated[
        typing.Optional[str],
        Field(description="New agent description."),
    ] = None,
    config: typing.Annotated[
        typing.Optional[AgentUpdateConfig],
        Field(description="Config fields to change."),
    ] = None,
    version_description: typing.Annotated[
        typing.Optional[str],
        Field(description="What changed, shown in version history. Only with `config`."),
    ] = None,
) -> dict[str, typing.Any]:
    if name is None and description is None and config is None:
        raise ValueError("Provide at least one of `name`, `description`, or `config`.")
    return _agent_with_playground_url(
        _api_client().agents.update(
            agent_id,
            name=_or_omit(name),
            description=_or_omit(description),
            config=_or_omit(config),
            version_description=_or_omit(version_description),
        )
    )


@mcp.tool(
    annotations=_destructive_tool("Delete agent"),
    description="""
        Permanently delete a Managed Agent. Confirm the agent's name with the
        user before calling this.
        """)
def delete_agent(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.delete(agent_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List agent calls"),
    description="""
        List a Managed Agent's calls, newest first, to debug them.

        Each row has the call `id`, `status`, `end_reason`, `error_message`,
        start and end times, `summary`, and `agent_version_id` (the config that
        ran). Pass a call `id` to `get_agent_call` for the transcript.

        Apps should not poll this for new calls; configure an event webhook
        on the agent instead.
        """)
def list_agent_calls(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`). The API requires it."),
    ],
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Calls per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: call ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return agent_call_list_to_result(
        sdk_page_to_result(
            _api_client().agents.calls.list(
                agent_id=agent_id,
                limit=_or_omit(limit),
                starting_after=_or_omit(starting_after),
                ending_before=_or_omit(ending_before),
            )
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent call"),
    description="""
        Get one Managed Agent call to debug it.

        By default (`detail="condensed"`) returns the outcome (`status`,
        `end_reason`, `error_message`, `summary`), `agent_version_id`,
        `dynamic_variables`, the connection, `latency_ms` (count, mean and max
        per metric, such as `llm_first_text_ms` and `agent_turn_ms`), and each
        turn's role, text, timing in seconds, interruption, TTS time to first
        byte, and tool calls with arguments and results (long results are
        truncated; `result_chars` is the full length). Pass `detail="full"` for the raw API payload.

        The agent's current config may have changed since the call. To read
        the config that actually ran, pass `agent_id` and `agent_version_id`
        to `get_agent_version`.
        """)
def get_agent_call(
    call_id: typing.Annotated[
        str,
        Field(min_length=1, description="Call ID (`ac_...`) from `list_agent_calls`."),
    ],
    detail: typing.Annotated[
        AgentCallDetail,
        Field(description="`condensed` (default) or `full` for the raw call JSON."),
    ] = "condensed",
) -> dict[str, typing.Any]:
    call = _api_client().agents.calls.retrieve(call_id).to_dict(mode="json")
    if detail == "full":
        return call
    return condense_agent_call(call)


@mcp.tool(
    annotations=_read_only_tool("List agent versions"),
    description="""
        List a Managed Agent's config versions, newest first.

        Every config change creates an immutable version. Rows have `id`,
        `created_at`, and `description`; call `get_agent_version` for the
        config.
        """)
def list_agent_versions(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Versions per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: version ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return agent_version_list_to_result(
        sdk_page_to_result(
            _api_client().agents.versions.list(
                agent_id,
                limit=_or_omit(limit),
                starting_after=_or_omit(starting_after),
                ending_before=_or_omit(ending_before),
            )
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent version"),
    description="""
        Get one Managed Agent config version: instructions, voice, model,
        tools, and the rest of the config as it was saved.

        Use the `agent_version_id` from `get_agent_call` to see the config a
        call ran with. Versions are read-only; there is no restore. To roll
        back, send this config to `update_agent`.
        """)
def get_agent_version(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    version_id: typing.Annotated[
        str,
        Field(min_length=1, description="Version ID (`av_...`)."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.versions.retrieve(version_id, agent_id=agent_id)
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_read_only_tool("List phone numbers"),
    description="""
        List the account's Managed Agents phone numbers and which agent each
        one routes inbound calls to (`agent`, or `null` when unassigned).

        Filter by `agent_id` to check whether an agent answers any number. Read
        only: this server does not provision, import, or reassign numbers, and
        does not place outbound calls.
        """)
def list_phone_numbers(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only numbers assigned to this agent for inbound calls."),
    ] = None,
    type: typing.Annotated[
        typing.Optional[PhoneNumberProviderType],
        Field(description="Provider type: `cartesia`, `twilio`, or `sip_trunk`."),
    ] = None,
    q: typing.Annotated[
        typing.Optional[str],
        Field(description="Search by number or label."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Numbers per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: phone number ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    page = _api_client().agents.phone_numbers.list(
        agent_id=_or_omit(agent_id),
        type=_or_omit(type),
        q=_or_omit(q),
        limit=_or_omit(limit),
        starting_after=_or_omit(starting_after),
        ending_before=_or_omit(ending_before),
    )
    return page_result([number.to_dict(mode="json") for number in page.data], page.has_more)


@mcp.tool(
    annotations=_read_only_tool("Get phone number"),
    description="""
        Get one Managed Agents phone number: the number, label, assigned agent,
        and provider (SIP trunk passwords are never returned).
        """)
def get_phone_number(
    phone_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID from `list_phone_numbers`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.phone_numbers.retrieve(phone_number_id).to_dict(mode="json")


AgentToolType = typing.Literal["webhook", "client"]
TwilioRegion = typing.Literal["us1", "ie1", "au1"]


def _agent_tool_page(page: typing.Any) -> dict[str, typing.Any]:
    rows = []
    for tool in page.data:
        raw = tool.to_dict(mode="json")
        row = {key: raw.get(key) for key in ("id", "name", "description", "type")}
        if raw.get("agents") is not None:
            row["agents"] = raw["agents"]
        rows.append(row)
    return page_result(rows, page.has_more, page.next_page)


@mcp.tool(
    annotations=_read_only_tool("List agent tools"),
    description="""
        List tools an agent can call during a conversation: `webhook` (Cartesia
        calls your HTTPS endpoint) and `client` (the caller's app runs it).

        Rows have `id`, `name`, `description`, and `type`. Call `get_agent_tool`
        for the request schema. Pass `expand` as `agents` to see which agents
        use each tool. Attach an id with `config.tools` on `create_agent` or
        `update_agent`.
        """,
)
def list_agent_tools(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only tools this agent uses."),
    ] = None,
    type: typing.Annotated[
        typing.Optional[AgentToolType],
        Field(description="`webhook` or `client`."),
    ] = None,
    expand: typing.Annotated[
        typing.Optional[list[typing.Literal["agents"]]],
        Field(description="`agents` includes the agents that use each tool."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Tools per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: tool ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return _agent_tool_page(
        _api_client().agents.tools.list(
            agent_id=_or_omit(agent_id),
            type=_or_omit(type),
            expand=_or_omit(expand),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent tool"),
    description="""
        Get one agent tool: its name, description, and how it runs.

        A webhook tool includes its URL, method, and parameter schemas.
        Credentials are write-only, so `secret_value` is never returned. Pass
        `expand` as `agents` to see which agents use it.
        """,
)
def get_agent_tool(
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID from `list_agent_tools`."),
    ],
    expand: typing.Annotated[
        typing.Optional[list[typing.Literal["agents"]]],
        Field(description="`agents` includes the agents that use this tool."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.tools.retrieve(tool_id, expand=_or_omit(expand))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Create agent tool"),
    description="""
        Create a tool an agent can call, then attach the returned `id` in
        `config.tools` on `create_agent` or `update_agent`.

        `type` is `webhook` (Cartesia sends an HTTPS request; put the URL and
        parameters in `api_schema`) or `client` (the caller's app handles the
        call; describe the arguments in `parameters`). `name` is what the agent
        says when it calls the tool, and `description` says when to use it.

        Credentials go in `secret_value` and are never returned. Do not put a
        secret in `secret_description`.
        """,
)
def create_agent_tool(
    tool: typing.Annotated[
        ToolCreateParams,
        Field(description="Webhook or client tool."),
    ],
) -> dict[str, typing.Any]:
    # The SDK types this as two overloads, which a spread union does not match.
    return (
        _api_client()
        .agents.tools.create(**typing.cast(typing.Any, tool))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update agent tool"),
    description="""
        Change an agent tool. Send only the fields to change.

        `api_schema`, `parameters`, and `assignments` replace the stored value,
        so send the whole object when editing one part. Call `get_agent_tool`
        first.
        """,
)
def update_agent_tool(
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID from `list_agent_tools`."),
    ],
    tool: typing.Annotated[
        ToolUpdateParams,
        Field(description="Fields to change."),
    ],
) -> dict[str, typing.Any]:
    if not tool:
        raise ValueError("Provide at least one field to change.")
    # The SDK types this as two overloads, which a spread union does not match.
    return (
        _api_client()
        .agents.tools.update(tool_id, **typing.cast(typing.Any, tool))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete agent tool"),
    description="""
        Delete an agent tool that no agent uses. Detach it from every agent's
        `config.tools` first, and confirm the tool's name with the user.
        """,
)
def delete_agent_tool(
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID from `list_agent_tools`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.tools.delete(tool_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


def _without_content(document: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Documents can hold up to 1 MB of text. Rows report its size; `get_knowledge_document` has it."""
    content = document.pop("content", None)
    if isinstance(content, str):
        document["content_chars"] = len(content)
    return document


@mcp.tool(
    annotations=_read_only_tool("List knowledge folders"),
    description="""
        List knowledge base folders with their documents and the agents that can
        search them. Returns top-level folders unless `parent_id` is set; nested
        folders come back in `children` up to `depth`. Documents filed at the
        root are in `root_documents`.

        Give an agent access by putting a folder or document id in
        `config.knowledge_base_folders` or `config.knowledge_base_documents` on
        `create_agent` or `update_agent`.
        """,
)
def list_knowledge_folders(
    parent_id: typing.Annotated[
        typing.Optional[str],
        Field(
            description="Only subfolders of this folder. Omit for top-level folders."
        ),
    ] = None,
    depth: typing.Annotated[
        typing.Optional[int],
        Field(
            ge=1,
            le=3,
            description="Levels of nested `children` to include (default 3).",
        ),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Top-level folders per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: folder ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    response = _api_client().agents.knowledge_base.folders.list(
        parent_ids=[parent_id] if parent_id else omit,
        depth=_or_omit(depth),
        limit=_or_omit(limit),
        starting_after=_or_omit(starting_after),
        ending_before=_or_omit(ending_before),
    )
    result = list_response_to_result(response)
    if response.root_documents:
        result["root_documents"] = [
            d.to_dict(mode="json") for d in response.root_documents
        ]
    return result


@mcp.tool(
    annotations=_read_only_tool("Get knowledge folder"),
    description="Get one knowledge base folder with its documents and the agents that can search it.",
)
def get_knowledge_folder(
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID from `list_knowledge_folders`."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.knowledge_base.folders.retrieve(folder_id)
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Create knowledge folder"),
    description="""
        Create a knowledge base folder. Names must be unique among siblings.
        Add documents with `create_knowledge_documents`, then attach the folder
        to an agent through `config.knowledge_base_folders`.
        """,
)
def create_knowledge_folder(
    name: typing.Annotated[str, Field(min_length=1, description="Folder name.")],
    parent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Parent folder ID. Omit for a top-level folder."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.knowledge_base.folders.create(name=name, parent_id=_or_omit(parent_id))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update knowledge folder"),
    description="""
        Rename a knowledge base folder or move it under another folder. Send only
        the fields to change. To move a document, use `update_knowledge_document`.
        """,
)
def update_knowledge_folder(
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID from `list_knowledge_folders`."),
    ],
    name: typing.Annotated[
        typing.Optional[str],
        Field(description="New name, unique among siblings."),
    ] = None,
    parent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Move the folder under this folder. Cannot create a cycle."),
    ] = None,
) -> dict[str, typing.Any]:
    if name is None and parent_id is None:
        raise ValueError("Provide at least one of name or parent_id.")
    return (
        _api_client()
        .agents.knowledge_base.folders.update(
            folder_id, name=_or_omit(name), parent_id=_or_omit(parent_id)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete knowledge folder"),
    description="""
        Permanently delete a knowledge base folder. Confirm the folder's name
        with the user first.

        Fails if the folder has subfolders or an agent can search it. Set `force`
        only after the user agrees: it also deletes every subfolder and document
        inside, and agents lose access to them.
        """,
)
def delete_knowledge_folder(
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID from `list_knowledge_folders`."),
    ],
    force: typing.Annotated[
        bool,
        Field(
            description="Delete even with subfolders or agents attached, and delete their contents."
        ),
    ] = False,
) -> dict[str, typing.Any]:
    _api_client().agents.knowledge_base.folders.delete(
        folder_id, force="true" if force else omit
    )
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List knowledge documents"),
    description="""
        List knowledge base documents. Rows have `id`, `name`, `status`
        (`processing`, `ready`, or `failed`), `error`, `metadata`, and
        `content_chars`. Call `get_knowledge_document` for the text.
        """,
)
def list_knowledge_documents(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Documents per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: document ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    result = sdk_page_to_result(
        _api_client().agents.knowledge_base.documents.list(
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )
    result["data"] = [_without_content(row) for row in result["data"]]
    return result


@mcp.tool(
    annotations=_read_only_tool("Get knowledge document"),
    description="Get one knowledge base document, including its text and processing `status`.",
)
def get_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.knowledge_base.documents.retrieve(document_id)
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Create knowledge documents"),
    description="""
        Upload 1 to 100 text documents agents can search during calls. Each needs
        `content` (up to 1 MB) and may set `name`, `folder_id`, and `metadata`
        (string values, used to filter retrieval). Use `file_id` instead of
        `content` only for a file already uploaded with purpose
        `knowledge_base_document`.

        Documents start as `processing`. Check `status` with
        `get_knowledge_document`, and use `retry_knowledge_document` on a
        `failed` one. Returns each document without its text.
        """,
)
def create_knowledge_documents(
    documents: typing.Annotated[
        list[KnowledgeDocumentInput],
        Field(min_length=1, max_length=100, description="Documents to upload."),
    ],
) -> dict[str, typing.Any]:
    created = _api_client().agents.knowledge_base.documents.create_bulk(
        documents=documents
    )
    return {"data": [_without_content(d.to_dict(mode="json")) for d in created]}


@mcp.tool(
    annotations=_destructive_tool("Update knowledge document"),
    description="""
        Change a knowledge base document's text, name, metadata, or folder. Send
        only the fields to change. New `content` replaces the old text and the
        document is processed again. Call `get_knowledge_document` first.
        """,
)
def update_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
    content: typing.Annotated[
        typing.Optional[str],
        Field(description="Replacement text (up to 1 MB)."),
    ] = None,
    name: typing.Annotated[
        typing.Optional[str], Field(description="New display name.")
    ] = None,
    folder_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Move the document into this folder."),
    ] = None,
    metadata: typing.Annotated[
        typing.Optional[dict[str, str]],
        Field(description="Metadata for retrieval filters, string values only."),
    ] = None,
) -> dict[str, typing.Any]:
    if content is None and name is None and folder_id is None and metadata is None:
        raise ValueError("Provide at least one field to change.")
    updated = _api_client().agents.knowledge_base.documents.update(
        document_id,
        content=_or_omit(content),
        name=_or_omit(name),
        folder_id=_or_omit(folder_id),
        metadata=_or_omit(metadata),
    )
    return _without_content(updated.to_dict(mode="json"))


@mcp.tool(
    annotations=_destructive_tool("Delete knowledge document"),
    description="""
        Permanently delete a knowledge base document. Confirm its name with the
        user first. Fails if an agent can search it; set `force` only after the
        user agrees, and agents will stop using it.
        """,
)
def delete_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
    force: typing.Annotated[
        bool,
        Field(description="Delete even if agents can search it."),
    ] = False,
) -> dict[str, typing.Any]:
    _api_client().agents.knowledge_base.documents.delete(
        document_id, force="true" if force else omit
    )
    return {"success": True}


@mcp.tool(
    annotations=_additive_tool("Retry knowledge document"),
    description="Process a knowledge base document again, for one whose `status` is `failed`.",
)
def retry_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
) -> dict[str, typing.Any]:
    retried = _api_client().agents.knowledge_base.documents.retry(document_id)
    return _without_content(retried.to_dict(mode="json"))


# ---------------------------------------------------------------------------
# Event webhooks
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_read_only_tool("List event webhooks"),
    description="""
        List event webhooks: HTTPS endpoints Cartesia POSTs call events to. Attach
        one to an agent with `config.event_webhook_id` on `create_agent` or
        `update_agent`. Secrets are write-only and never returned.
        """,
)
def list_event_webhooks(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Webhooks per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: webhook ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return sdk_page_to_result(
        _api_client().agents.webhooks.list(
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get event webhook"),
    description="Get one event webhook's URL and name. The secret is never returned.",
)
def get_event_webhook(
    webhook_id: typing.Annotated[
        str,
        Field(min_length=1, description="Webhook ID from `list_event_webhooks`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.webhooks.retrieve(webhook_id).to_dict(mode="json")


@mcp.tool(
    annotations=_additive_tool("Create event webhook"),
    description="""
        Create an event webhook. Cartesia POSTs call events to `url` and sends
        `secret` back in the `X-Webhook-Secret` header so your endpoint can verify
        the request. The secret is write-only and is not echoed in the result.
        Attach the returned `id` to an agent with `config.event_webhook_id`.
        """,
)
def create_event_webhook(
    url: typing.Annotated[
        str, Field(min_length=1, description="HTTPS endpoint to receive events.")
    ],
    secret: typing.Annotated[
        str,
        Field(min_length=1, description="Shared secret sent in `X-Webhook-Secret`."),
    ],
    display_name: typing.Annotated[
        typing.Optional[str],
        Field(description="Name to identify the webhook."),
    ] = None,
) -> dict[str, typing.Any]:
    created = _api_client().agents.webhooks.create(
        url=url, secret=secret, display_name=_or_omit(display_name)
    )
    result = created.to_dict(mode="json")
    result.pop("secret", None)
    return result


@mcp.tool(
    annotations=_destructive_tool("Update event webhook"),
    description="""
        Change an event webhook. `url` is required even when unchanged. Omit
        `secret` to keep the stored one. Agents using this webhook start sending
        events to the new URL right away, so confirm the change with the user.
        """,
)
def update_event_webhook(
    webhook_id: typing.Annotated[
        str,
        Field(min_length=1, description="Webhook ID from `list_event_webhooks`."),
    ],
    url: typing.Annotated[
        str, Field(min_length=1, description="HTTPS endpoint to receive events.")
    ],
    display_name: typing.Annotated[
        typing.Optional[str],
        Field(description="New name."),
    ] = None,
    secret: typing.Annotated[
        typing.Optional[str],
        Field(description="New shared secret. Omit to keep the current one."),
    ] = None,
) -> dict[str, typing.Any]:
    _api_client().agents.webhooks.update(
        webhook_id,
        url=url,
        display_name=_or_omit(display_name),
        secret=_or_omit(secret),
    )
    return {"success": True}


@mcp.tool(
    annotations=_destructive_tool("Delete event webhook"),
    description="""
        Permanently delete an event webhook. Confirm its name and URL with the
        user first, since agents using it stop sending events.
        """,
)
def delete_event_webhook(
    webhook_id: typing.Annotated[
        str,
        Field(min_length=1, description="Webhook ID from `list_event_webhooks`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.webhooks.delete(webhook_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_read_only_tool("List agent metrics"),
    description="""
        List evaluation metrics. A metric is a prompt an LLM runs over finished
        calls to score them. Metrics apply to the agents they are attached to
        with `attach_agent_metric`; read scores with `list_agent_metric_results`.
        """,
)
def list_agent_metrics(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Metrics per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
) -> dict[str, typing.Any]:
    return list_response_to_result(
        _api_client().agents.metrics.list(
            limit=_or_omit(limit), starting_after=_or_omit(starting_after)
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent metric"),
    description="Get one evaluation metric with its `name` and scoring `prompt`.",
)
def get_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.metrics.retrieve(metric_id).to_dict(mode="json")


@mcp.tool(
    annotations=_additive_tool("Create agent metric"),
    description="""
        Create an evaluation metric. `prompt` describes the task and the criteria
        an LLM uses to score a finished call, for example "Did the agent confirm
        the caller's appointment time?". `name` must be unique. The metric does
        nothing until you call `attach_agent_metric`.
        """,
)
def create_agent_metric(
    name: typing.Annotated[
        str,
        Field(min_length=1, description="Unique identifier for the metric."),
    ],
    prompt: typing.Annotated[
        str,
        Field(min_length=1, description="Task and scoring criteria."),
    ],
    display_name: typing.Annotated[
        typing.Optional[str],
        Field(description="Name shown in the playground."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.metrics.create(
            name=name, prompt=prompt, display_name=_or_omit(display_name)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete agent metric"),
    description="""
        Permanently delete an evaluation metric. Confirm its name with the user
        first. Agents stop scoring calls with it.
        """,
)
def delete_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.metrics.delete(metric_id)
    return {"success": True}


@mcp.tool(
    annotations=_additive_tool("Attach agent metric"),
    description="Score an agent's finished calls with a metric from now on.",
)
def attach_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
    agent_id: typing.Annotated[str, Field(min_length=1, description="Agent ID.")],
) -> dict[str, typing.Any]:
    _api_client().agents.metrics.add_to_agent(metric_id, agent_id=agent_id)
    return {"success": True}


@mcp.tool(
    annotations=_destructive_tool("Detach agent metric"),
    description="""
        Stop scoring an agent's calls with a metric. Existing results stay.
        Confirm the metric and agent with the user first.
        """,
)
def detach_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
    agent_id: typing.Annotated[str, Field(min_length=1, description="Agent ID.")],
) -> dict[str, typing.Any]:
    _api_client().agents.metrics.remove_from_agent(metric_id, agent_id=agent_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List agent metric results"),
    description="""
        List evaluation scores for finished calls, newest first. Each result has
        `metricName`, `status`, `result`, `summary`, and `value`. Filter by agent,
        call, metric, or `start_date` and `end_date` (ISO 8601). Use
        `export_agent_metric_results` for a CSV of many rows.
        """,
)
def list_agent_metric_results(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this agent."),
    ] = None,
    call_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this call."),
    ] = None,
    metric_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this metric."),
    ] = None,
    start_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or after this ISO 8601 time."),
    ] = None,
    end_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or before this ISO 8601 time."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Results per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: result ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return sdk_page_to_result(
        _api_client().agents.metrics.results.list(
            agent_id=_or_omit(agent_id),
            call_id=_or_omit(call_id),
            metric_id=_or_omit(metric_id),
            start_date=_or_omit(start_date),
            end_date=_or_omit(end_date),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


EXPORT_RESULTS_MAX_CHARS = 100_000


@mcp.tool(
    annotations=_read_only_tool("Export agent metric results"),
    description="""
        Export evaluation scores as CSV text, up to 100k rows from the API and
        100,000 characters here. When `truncated` is true, narrow the filters.
        """,
)
def export_agent_metric_results(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this agent."),
    ] = None,
    call_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this call."),
    ] = None,
    metric_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this metric."),
    ] = None,
    start_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or after this ISO 8601 time."),
    ] = None,
    end_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or before this ISO 8601 time."),
    ] = None,
) -> dict[str, typing.Any]:
    csv = _api_client().agents.metrics.results.export(
        agent_id=_or_omit(agent_id),
        call_id=_or_omit(call_id),
        metric_id=_or_omit(metric_id),
        start_date=_or_omit(start_date),
        end_date=_or_omit(end_date),
    )
    return {
        "csv": csv[:EXPORT_RESULTS_MAX_CHARS],
        "truncated": len(csv) > EXPORT_RESULTS_MAX_CHARS,
        "total_chars": len(csv),
    }


# ---------------------------------------------------------------------------
# Phone numbers and telephony providers
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_real_world_tool("Provision phone number"),
    description="""
        Buy a new Cartesia-managed phone number. This can incur charges and cannot
        be undone from here. Only call it after the user has confirmed, in this
        conversation, that they want a new number, plus its label and the agent
        that should answer it.

        Cartesia numbers take inbound calls and outbound calls to US numbers. Pass
        `agent_id` to answer inbound calls with that agent; omit it to keep the
        number outbound-only.
        """,
)
def provision_phone_number(
    label: typing.Annotated[
        str,
        Field(min_length=1, description="Human-readable name for the number."),
    ],
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Agent that answers inbound calls. Omit for outbound-only."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.provision(label=label, agent_id=_or_omit(agent_id))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Import phone number"),
    description="""
        Link a number you already own to Cartesia through a provider from
        `list_phone_providers`. `provider` is `{"id": "<provider id>"}`, or
        `{"type": "twilio", "account_sid": "...", "region": "us1"}` to look the
        provider up by Twilio account. The number must be in that account.

        With `agent_id`, inbound calls to the number start answering with that
        agent, so confirm the number and agent with the user first.
        """,
)
def import_phone_number(
    label: typing.Annotated[
        str,
        Field(min_length=1, description="Human-readable name for the number."),
    ],
    number: typing.Annotated[
        str,
        Field(
            min_length=1,
            description="Phone number in E.164 format, such as `+14155551234`.",
        ),
    ],
    provider: typing.Annotated[
        ImportProvider,
        Field(description="Existing provider by id, or a Twilio account lookup."),
    ],
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Agent that answers inbound calls. Omit for outbound-only."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.import_(
            label=label, number=number, provider=provider, agent_id=_or_omit(agent_id)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update phone number"),
    description="""
        Change a phone number's label, the agent answering its inbound calls, or
        its provider. Send only the fields to change.

        Changing the agent reroutes live inbound calls: confirm the number
        (`get_phone_number`) and the new agent with the user first. Set
        `unassign_agent` to stop answering inbound calls. Moving between provider
        types is not supported; delete and re-import instead.
        """,
)
def update_phone_number(
    phone_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID from `list_phone_numbers`."),
    ],
    label: typing.Annotated[
        typing.Optional[str],
        Field(description="New name."),
    ] = None,
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Agent that answers inbound calls from now on."),
    ] = None,
    unassign_agent: typing.Annotated[
        bool,
        Field(
            description="Stop answering inbound calls. Cannot be combined with `agent_id`."
        ),
    ] = False,
    provider_id: typing.Annotated[
        typing.Optional[str],
        Field(
            description="Move the number to this provider ID from `list_phone_providers`."
        ),
    ] = None,
) -> dict[str, typing.Any]:
    if agent_id is not None and unassign_agent:
        raise ValueError("Pass agent_id or unassign_agent, not both.")
    if (
        label is None
        and agent_id is None
        and not unassign_agent
        and provider_id is None
    ):
        raise ValueError("Provide at least one field to change.")
    return (
        _api_client()
        .agents.phone_numbers.update(
            phone_number_id,
            label=_or_omit(label),
            agent_id=None if unassign_agent else _or_omit(agent_id),
            provider={"id": provider_id} if provider_id else omit,
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete phone number"),
    description="""
        Permanently remove a phone number from Cartesia. A Cartesia-managed number
        may not be recoverable, and inbound calls to it stop working. Fetch it with
        `get_phone_number` and confirm the exact number with the user first.
        """,
)
def delete_phone_number(
    phone_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID from `list_phone_numbers`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.phone_numbers.delete(phone_number_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List phone providers"),
    description="""
        List telephony providers (Twilio accounts and SIP trunks) linked to your
        account. Secrets are write-only and never returned.
        """,
)
def list_phone_providers(
    type: typing.Annotated[
        typing.Optional[typing.Literal["twilio", "sip_trunk"]],
        Field(description="Only this provider type."),
    ] = None,
    account_sid: typing.Annotated[
        typing.Optional[str],
        Field(description="Only this Twilio account SID."),
    ] = None,
) -> dict[str, typing.Any]:
    providers = _api_client().agents.phone_numbers.providers.list(
        type=_or_omit(type), account_sid=_or_omit(account_sid)
    )
    return {"data": [p.to_dict(mode="json") for p in providers]}


@mcp.tool(
    annotations=_read_only_tool("Get phone provider"),
    description="Get one telephony provider. Secrets are never returned.",
)
def get_phone_provider(
    provider_id: typing.Annotated[
        str,
        Field(min_length=1, description="Provider ID from `list_phone_providers`."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.providers.retrieve(provider_id)
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Create Twilio provider"),
    description="""
        Link a Twilio account so its numbers can be imported with
        `import_phone_number`. Cartesia checks the credentials with Twilio first.
        Each account SID and region can be linked once. `api_key_secret` is
        write-only. SIP trunk providers are not supported here yet.
        """,
)
def create_twilio_provider(
    account_sid: typing.Annotated[
        str, Field(min_length=1, description="Twilio account SID.")
    ],
    api_key_sid: typing.Annotated[
        str, Field(min_length=1, description="Twilio API key SID.")
    ],
    api_key_secret: typing.Annotated[
        str,
        Field(min_length=1, description="Twilio API key secret."),
    ],
    region: typing.Annotated[
        typing.Optional[TwilioRegion],
        Field(description="Twilio region: `us1` (default), `ie1`, or `au1`."),
    ] = None,
    label: typing.Annotated[
        typing.Optional[str],
        Field(description="Human-readable name for the provider."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.providers.create(
            type="twilio",
            account_sid=account_sid,
            api_key_sid=api_key_sid,
            api_key_secret=api_key_secret,
            region=_or_omit(region),
            label=_or_omit(label),
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update phone provider"),
    description="""
        Change a telephony provider. `provider.type` is required: `twilio` takes
        new `api_key_sid` and `api_key_secret`; `sip_trunk` takes optional `label`,
        `inbound`, and `outbound` settings, and omitted fields stay as they are.
        Numbers on the provider use the new settings immediately, so confirm the
        provider with the user first. Call `get_phone_provider` beforehand.
        """,
)
def update_phone_provider(
    provider_id: typing.Annotated[
        str,
        Field(min_length=1, description="Provider ID from `list_phone_providers`."),
    ],
    provider: typing.Annotated[
        ProviderUpdateParams,
        Field(description="Twilio or SIP trunk fields to change."),
    ],
) -> dict[str, typing.Any]:
    # The SDK types this as overloads, which a spread union does not match.
    return (
        _api_client()
        .agents.phone_numbers.providers.update(
            provider_id, **typing.cast(typing.Any, provider)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete phone provider"),
    description="""
        Unlink a telephony provider. Numbers that use it stop working. Fetch it
        with `get_phone_provider` and confirm it with the user first.
        """,
)
def delete_phone_provider(
    provider_id: typing.Annotated[
        str,
        Field(min_length=1, description="Provider ID from `list_phone_providers`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.phone_numbers.providers.delete(provider_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Outbound calls and call batches
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_real_world_tool("Create outbound agent calls"),
    description="""
        Place real outbound phone calls with an agent. Every destination rings a
        real person and may cost money, and a call cannot be recalled once placed
        (`cancel_agent_call` only stops one that has not connected). Only call
        this after the user has confirmed, in this conversation, the exact
        numbers to dial, the agent, and the number to call from.

        `from_number_id` comes from `list_phone_numbers`. Each entry in
        `outbound_calls` has `to_number` in E.164 format and optional
        `dynamic_variables` for the agent's welcome message. Each result in
        `calls` has an `agent_call_id` for `get_agent_call`, or an `error`. For
        many numbers use `create_call_batch`.
        """,
)
def create_agent_calls(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Agent that handles the calls."),
    ],
    from_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID to call from."),
    ],
    outbound_calls: typing.Annotated[
        list[OutboundCall],
        Field(min_length=1, description="Destinations and per-call dynamic variables."),
    ],
    max_call_duration_minutes: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Maximum call length in minutes."),
    ] = None,
    ringing_timeout_seconds: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Seconds to wait for an answer (default 60)."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.calls.create(
            agent_id=agent_id,
            from_number_id=from_number_id,
            outbound_calls=outbound_calls,
            max_call_duration_minutes=_or_omit(max_call_duration_minutes),
            ringing_timeout_seconds=_or_omit(ringing_timeout_seconds),
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Cancel agent call"),
    description="""
        Cancel an outbound call that has not connected yet. It does not hang up a
        call in progress. Confirm the call with the user first.
        """,
)
def cancel_agent_call(
    call_id: typing.Annotated[
        str,
        Field(
            min_length=1,
            description="Call ID from `create_agent_calls` or `list_agent_calls`.",
        ),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.cancel(call_id).to_dict(mode="json")


@mcp.tool(
    annotations=_destructive_tool("Delete agent call"),
    description="""
        Permanently delete a call record with its transcript and recording.
        Confirm the call (`get_agent_call`) with the user first.
        """,
)
def delete_agent_call(
    call_id: typing.Annotated[
        str,
        Field(min_length=1, description="Call ID from `list_agent_calls`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.calls.delete(call_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List call batches"),
    description="""
        List outbound call batches, newest first, without per-recipient detail.
        Call `get_call_batch` for recipients.
        """,
)
def list_call_batches(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only batches for this agent."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Batches per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: batch ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    result = sdk_page_to_result(
        _api_client().agents.calls.batches.list(
            agent_id=_or_omit(agent_id),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )
    for row in result["data"]:
        row.pop("recipients", None)
    return result


@mcp.tool(
    annotations=_read_only_tool("Get call batch"),
    description="""
        Get one call batch: its `status`, progress counters, and each recipient's
        status and `agent_call_id`.
        """,
)
def get_call_batch(
    batch_id: typing.Annotated[
        str,
        Field(min_length=1, description="Batch ID from `list_call_batches`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.batches.retrieve(batch_id).to_dict(mode="json")


@mcp.tool(
    annotations=_real_world_tool("Create call batch"),
    description="""
        Start an outbound call batch: one agent dials many recipients. Every
        recipient rings a real person and may cost money. Only call this after
        the user has confirmed, in this conversation, the full recipient list (or
        its count and source), the agent, the number to call from, and the start
        time. Use `cancel_call_batch` to stop dialing.

        Dialing starts immediately unless `scheduled_at` is set (RFC 3339 with a
        timezone, in the future, within 30 days). `from_number_id` comes from
        `list_phone_numbers`. `target_concurrency_limit` caps simultaneous calls
        and defaults to half the organization's limit. `region` applies to
        SIP-trunk numbers only.
        """,
)
def create_call_batch(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Agent that handles the batch's calls."),
    ],
    from_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID to call from."),
    ],
    name: typing.Annotated[
        str, Field(min_length=1, description="Label for the batch.")
    ],
    recipients: typing.Annotated[
        list[OutboundCall],
        Field(min_length=1, description="Destinations and per-call dynamic variables."),
    ],
    scheduled_at: typing.Annotated[
        typing.Optional[str],
        Field(description="Start time as RFC 3339 with timezone. Omit to dial now."),
    ] = None,
    target_concurrency_limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Maximum simultaneous calls."),
    ] = None,
    max_call_duration_minutes: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Maximum call length in minutes (default 480)."),
    ] = None,
    ringing_timeout_seconds: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Seconds to wait for an answer (default 60)."),
    ] = None,
    region: typing.Annotated[
        typing.Optional[typing.Literal["US", "EU", "APAC"]],
        Field(description="Dispatch region, for SIP-trunk numbers only."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.calls.batches.create(
            agent_id=agent_id,
            from_number_id=from_number_id,
            name=name,
            recipients=recipients,
            scheduled_at=_or_omit(scheduled_at),
            target_concurrency_limit=_or_omit(target_concurrency_limit),
            max_call_duration_minutes=_or_omit(max_call_duration_minutes),
            ringing_timeout_seconds=_or_omit(ringing_timeout_seconds),
            region=_or_omit(region),
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Cancel call batch"),
    description="""
        Stop dialing a call batch. Calls already connected continue. Confirm the
        batch (`get_call_batch`) with the user first.
        """,
)
def cancel_call_batch(
    batch_id: typing.Annotated[
        str,
        Field(min_length=1, description="Batch ID from `list_call_batches`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.batches.cancel(batch_id).to_dict(mode="json")


@mcp.tool(
    annotations=_real_world_tool("Retry call batch"),
    description="""
        Dial a finished batch's failed recipients again. Those recipients ring
        real people and may cost money, so only call this after the user has
        confirmed which batch to retry. Check `get_call_batch` first.
        """,
)
def retry_call_batch(
    batch_id: typing.Annotated[
        str,
        Field(min_length=1, description="Batch ID from `list_call_batches`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.batches.retry(batch_id).to_dict(mode="json")


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_read_only_tool("Get agent usage"),
    description="""
        Returns Managed Agents usage over time (`GET /usage/agents`): `cents`
        spent, `minutes` of calls, and number of `calls` per bucket.

        Requires **CARTESIA_ADMIN_API_KEY** (admin API keys cannot be used as CARTESIA_API_KEY).
        Optional `start_ts` and `end_ts` are RFC 3339 datetimes, at most 366 days
        apart; `interval` buckets results by `day`, `week`, or `month`. Without
        `interval` the result is one total for the window.
        """,
)
def get_agent_usage(
    start_ts: typing.Annotated[
        typing.Optional[str],
        Field(description="Start of the usage window (ISO 8601 timestamp)."),
    ] = None,
    end_ts: typing.Annotated[
        typing.Optional[str],
        Field(description="End of the usage window (ISO 8601 timestamp)."),
    ] = None,
    interval: typing.Annotated[
        typing.Optional[UsageInterval],
        Field(description="Bucket size for the returned usage time series."),
    ] = None,
) -> dict[str, typing.Any]:
    return extra_api.get_usage_agents(
        _require_admin_client(), start_ts=start_ts, end_ts=end_ts, interval=interval
    )


@mcp.tool(
    annotations=_additive_tool("Add voice accents"),
    description="""
        Add accents to an instant voice clone you own so a single voice_id can speak
        multiple accents natively. A voice can support up to 10 accents in total,
        including native.
        """)
def add_voice_accents(
    voice_id: typing.Annotated[
        str,
        Field(description="The ID of the voice."),
    ],
    accents: typing.Annotated[
        list[AttachVoiceAccent],
        Field(description="Catalog accent ids from GET /accents (for example `british` or `parisian`). Display names are rejected on this API version."),
    ],
) -> Voice:
    voice = _api_client().voices.add_accents(
        id=voice_id,
        accents=accents,
    )
    return coerce_null_voice_locales(voice)


@mcp.tool(
    annotations=_destructive_tool("Delete voice accent"),
    description="""
        Remove an accent an instant voice clone supports.
        """)
def delete_voice_accent(
    voice_id: typing.Annotated[
        str,
        Field(description="The ID of the voice."),
    ],
    accent: typing.Annotated[
        VoiceAccent,
        Field(description="Catalog accent id from GET /accents (for example `british` or `parisian`). Display names are rejected on this API version."),
    ],
) -> Voice:
    voice = _api_client().voices.delete_accent(
        accent,
        id=voice_id,
    )
    return coerce_null_voice_locales(voice)


@mcp.tool(
    annotations=_additive_tool("Clone voice"),
    description="""
        Clone a voice from an audio clip. This endpoint has two modes, stability and similarity.
        
        Similarity mode clones are more similar to the source clip, but may reproduce background noise. For these, use an audio clip about 5 seconds long.
        
        Stability mode clones are more stable, but may not sound as similar to the source clip. For these, use an audio clip 10-20 seconds long.
        
        Pass `file_id` or `file_path`, not both. On hosted MCP, pass the `file_id`
        from `text_to_speech` or `download_file`. `file_path` is an absolute path on
        this MCP server (local `uvx`, or a path returned in this same session). A path
        on the agent machine is not visible to hosted MCP and returns a validation
        error — use `file_id` instead.
        """)
def clone_voice(
    name: typing.Annotated[
        str,
        Field(description="The name of the voice."),
    ],
    language: typing.Annotated[
        SupportedLanguage,
        Field(description="The language of the voice."),
    ],
    mode: typing.Annotated[
        str,
        Field(description="Tradeoff between similarity and stability. Similarity clones sound more like the source clip, but may reproduce background noise. Stability clones always sound like a studio recording, but may not sound as similar to the source clip."),
    ],
    file_path: typing.Annotated[
        typing.Optional[str],
        Field(description="Absolute path on this MCP server. Must exist; hosted MCP only accepts files this server wrote (from `download_file` or `save=false` TTS)."),
    ] = None,
    file_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Cartesia cloud file id. The server downloads it."),
    ] = None,
    description: typing.Annotated[
        typing.Optional[str],
        Field(description="A description for the voice."),
    ] = None,
    accent: typing.Annotated[
        typing.Optional[VoiceAccent],
        Field(description="Catalog accent id from GET /accents (for example `southern-us` or `parisian`). Display names are rejected on this API version. Omit to leave unset."),
    ] = None,
) -> VoiceMetadata:
    source = _resolve_audio_input(file_path, file_id)
    clone_kwargs: dict[str, typing.Any] = {}
    _merge_extra_body(clone_kwargs, {"mode": mode})
    with open(source, "rb") as clip:
        return _api_client().voices.clone(
            clip=clip,
            name=name,
            language=language,
            description=description,
            accent=accent if accent is not None else omit,
            **clone_kwargs,
        )

@mcp.tool(
    annotations=_read_only_tool("List voices"),
    description="""
        List voices available to you (your own and Cartesia library voices), with search, filters, and cursor pagination.
        """)
def list_voices(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(description="The number of Voices to return per page, ranging between 1 and 100."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="A cursor to use in pagination. `starting_after` is a Voice ID that defines your place in the list. For example, if you make a /voices request and receive 100 objects, ending with `voice_abc123`, your subsequent call can include `starting_after=voice_abc123` to fetch the next page of the list."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="A cursor to use in pagination. `ending_before` is a Voice ID that defines your place in the list. For example, if you make a /voices request and receive 100 objects, starting with `voice_abc123`, your subsequent call can include `ending_before=voice_abc123` to fetch the previous page of the list."),
    ] = None,
    is_owner: typing.Annotated[
        typing.Optional[bool],
        Field(description="Whether to only return voices owned by the current user."),
    ] = None,
    is_starred: typing.Annotated[
        typing.Optional[bool],
        Field(description="Whether to only return starred voices."),
    ] = None,
    gender: typing.Annotated[
        typing.Optional[GenderPresentation],
        Field(description="The gender presentation of the voices to return."),
    ] = None,
    language: typing.Annotated[
        typing.Optional[str],
        Field(description="Filter voices by language or locale, such as `en`, `it`, or `en_GB`. A locale returns accents for that region; a language alone returns all accents for that language. Both `-` and `_` separators are accepted."),
    ] = None,
    q: typing.Annotated[
        typing.Optional[str],
        Field(description="Search voices by name, description, or voice ID."),
    ] = None,
    expand: typing.Annotated[
        typing.Optional[typing.Sequence[typing.Literal["preview_file_url"]]],
        Field(description="Additional fields to include in the response, such as `preview_file_url`."),
    ] = None,
) -> ListVoicesResult:
    extra_query: dict[str, typing.Any] = {}
    if language is not None:
        extra_query["language"] = language
    if is_starred is not None:
        extra_query["is_starred"] = is_starred
    pager = _api_client().voices.list(
        limit=limit,
        gender=gender,
        is_owner=is_owner,
        starting_after=starting_after,
        ending_before=ending_before,
        q=q,
        expand=list(expand) if expand else omit,
        extra_query=extra_query or None,
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
) -> STTTranscribeResponse:
    with open(file_path, "rb") as audio_file:
        kwargs: dict[str, typing.Any] = {
            "file": audio_file,
            "model": model,
        }
        if language is not None:
            kwargs["language"] = language
        if encoding is not None:
            kwargs["encoding"] = encoding
        if sample_rate is not None:
            kwargs["sample_rate"] = sample_rate
        if timestamp_granularities is not None:
            kwargs["timestamp_granularities"] = list(timestamp_granularities)
        return _api_client().stt.transcribe(**kwargs)


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


@mcp.tool(
    annotations=_read_only_tool("Transcribe audio"),
    description="""
        Transcribe a pre-recorded audio file to text.
        
        **Default (`mode="batch"`):** upload the file via batch STT (`POST /stt`).
        Best for typical MCP file-on-disk tasks (mp3, flac, wav, and other containers).
        Default model: `ink-whisper`.
        
        **Streaming (`mode="stream"`):** send mono PCM over STT WebSocket (`/stt/websocket`).
        Use for mono PCM WAV (for example TTS output) or raw PCM with `encoding` and
        `sample_rate`. Default model: `ink-2`.
        
        **Pricing:** See [STT pricing](https://docs.cartesia.ai/pricing#speech-to-text).
        
        Pass `file_id` or `file_path`, not both. On hosted MCP, pass the `file_id`
        from `text_to_speech` or `download_file`. Do not pass a path from the agent
        machine — `file_path` is an absolute path on this MCP server and must exist.
        A missing path on hosted MCP returns a validation error telling you to use
        `file_id`.
        """)
def speech_to_text(
    file_path: typing.Annotated[
        typing.Optional[str],
        Field(description="Absolute path on this MCP server. Must exist; hosted MCP only accepts files this server wrote (from `download_file` or `save=false` TTS)."),
    ] = None,
    mode: typing.Annotated[
        SttMode,
        Field(description="`batch` (default) or `stream`."),
    ] = "batch",
    model: typing.Annotated[
        typing.Optional[str],
        Field(description="STT model ID. Defaults to `ink-whisper` for batch and `ink-2` for stream. Call `list_models` with `capability=\"stt\"` for valid ids."),
    ] = None,
    language: typing.Annotated[
        typing.Optional[str],
        Field(description="ISO-639-1 language code (defaults to `en` for stream; batch uses API default)."),
    ] = None,
    encoding: typing.Annotated[
        typing.Optional[STTEncoding],
        Field(description="Required for raw PCM without a container header (both modes)."),
    ] = None,
    sample_rate: typing.Annotated[
        typing.Optional[int],
        Field(description="Sample rate in Hz when `encoding` is set."),
    ] = None,
    timestamp_granularities: typing.Annotated[
        typing.Optional[typing.Sequence[typing.Literal["word"]]],
        Field(description="Pass `[\"word\"]` for word-level timestamps when supported."),
    ] = None,
    file_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Cartesia cloud file id. The server downloads it. Use this from hosted clients."),
    ] = None,
) -> STTTranscribeResponse:
    source = _resolve_audio_input(
        file_path, file_id
    )
    stt_model = _resolve_stt_model(mode, model)
    if mode == "stream":
        return _speech_to_text_stream(
            file_path=source,
            model=stt_model,
            language=language,
            encoding=encoding,
            sample_rate=sample_rate,
            timestamp_granularities=timestamp_granularities,
        )
    return _speech_to_text_batch(
        file_path=source,
        model=stt_model,
        language=language,
        encoding=encoding,
        sample_rate=sample_rate,
        timestamp_granularities=timestamp_granularities,
    )


@mcp.tool(
    annotations=_read_only_tool("Download file"),
    description="""
        Fetch a Cartesia cloud-stored file by ID. Returns a 24-hour `download_url` for
        hosted and remote clients. Also writes a copy to `OUTPUT_DIRECTORY` on the MCP
        server host (for local `uvx` or server-side `speech_to_text` in the same session).
        On hosted MCP those local copies are under a temp directory and purged after a TTL.
        
        Use the `file_id` from a prior `text_to_speech` call (`save=true`, the default)
        or from playground TTS history.
        """)
def download_file(
    file_id: typing.Annotated[
        str,
        Field(description="Cloud file ID (e.g. from `text_to_speech`)."),
    ],
    format: typing.Annotated[
        typing.Optional[DownloadFormat],
        Field(description="Pass `playback` to wrap raw PCM as WAV in the download link and local file."),
    ] = None,
) -> DownloadedFileResult:
    return _deliver_cloud_file(file_id, format=format)


@mcp.tool(
    annotations=_read_only_tool("Get credit usage"),
    description="""
        Returns credit usage over time (`GET /usage/credits`).
        
        Requires **CARTESIA_ADMIN_API_KEY** (admin API keys cannot be used as CARTESIA_API_KEY).
        Optional `start_ts` and `end_ts` are RFC 3339 datetimes;
        `interval` buckets results by `day`, `week`, or `month`.
        """)
def get_credit_usage(
    start_ts: typing.Annotated[
        typing.Optional[str],
        Field(description="Start of the usage window (ISO 8601 timestamp)."),
    ] = None,
    end_ts: typing.Annotated[
        typing.Optional[str],
        Field(description="End of the usage window (ISO 8601 timestamp)."),
    ] = None,
    interval: typing.Annotated[
        typing.Optional[UsageInterval],
        Field(description="Bucket size for the returned usage time series."),
    ] = None,
    api_key_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Limit usage to a specific API key ID."),
    ] = None,
    group_by: typing.Annotated[
        typing.Optional[UsageCreditsGroupBy],
        Field(description="Break down usage by capability, model, voice, or API key. When `interval` is set it must be `day`. Grouped responses use `{ group_by, data: [{ id, label?, buckets }] }`."),
    ] = None,
) -> dict[str, typing.Any]:
    return extra_api.get_usage_credits(
        _require_admin_client(),
        start_ts=start_ts,
        end_ts=end_ts,
        interval=interval,
        api_key_id=api_key_id,
        group_by=group_by,
    )


@mcp.tool(
    annotations=_read_only_tool("List pronunciation dictionaries"),
    description="""
        List pronunciation dictionaries for the authenticated user.
        """)
def list_pronunciation_dicts(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(description="Number of dictionaries per page (1–100)."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: dictionary ID to start after."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: dictionary ID to end before."),
    ] = None,
) -> ListPronunciationDictsResult:
    page = client.pronunciation_dicts.list(
        limit=limit,
        starting_after=starting_after,
        ending_before=ending_before,
    )
    return typing.cast(ListPronunciationDictsResult, cursor_page_to_result(page))


def _pronunciation_dict_items_for_sdk(
    items: typing.Sequence[PronunciationDictItemParams],
) -> list[dict[str, typing.Any]]:
    return [
        {
            "text": item["text"],
            "alias": item["pronunciation"],
            "case_sensitive": item.get("case_sensitive", False),
        }
        for item in items
    ]


@mcp.tool(
    annotations=_additive_tool("Create pronunciation dictionary"),
    description="""
        Create a pronunciation dictionary.
        """)
def create_pronunciation_dict(
    name: typing.Annotated[
        str,
        Field(description="Name of the pronunciation dictionary."),
    ],
    items: typing.Annotated[
        typing.Optional[typing.Sequence[PronunciationDictItemParams]],
        Field(description="Mappings of `text` to `pronunciation` (IPA or sounds-like). Optional `case_sensitive` (default false): when false, match every capitalization of `text` on Sonic 3.6."),
    ] = None,
) -> dict[str, typing.Any]:
    return client.pronunciation_dicts.create(
        name=name,
        items=_pronunciation_dict_items_for_sdk(items) if items is not None else omit,
    ).model_dump(mode="json")


@mcp.tool(
    annotations=_read_only_tool("Get pronunciation dictionary"),
    description="""
        Get a pronunciation dictionary and its items by ID.
        """)
def get_pronunciation_dict(
    dict_id: typing.Annotated[
        str,
        Field(description="Pronunciation dictionary ID."),
    ],
) -> dict[str, typing.Any]:
    return client.pronunciation_dicts.retrieve(dict_id).model_dump(mode="json")


@mcp.tool(
    annotations=_destructive_tool("Update pronunciation dictionary"),
    description="""
        Update a pronunciation dictionary.
        """)
def update_pronunciation_dict(
    dict_id: typing.Annotated[
        str,
        Field(description="The ID of the pronunciation dictionary to update."),
    ],
    name: typing.Annotated[
        typing.Optional[str],
        Field(description="New name for the pronunciation dictionary."),
    ] = None,
    items: typing.Annotated[
        typing.Optional[typing.Sequence[PronunciationDictItemParams]],
        Field(description="Optional `case_sensitive` (default false) on each item."),
    ] = None,
) -> dict[str, typing.Any]:
    if name is None and items is None:
        raise ValueError("At least one of `name` or `items` must be provided.")
    kwargs: dict[str, typing.Any] = {}
    if name is not None:
        kwargs["name"] = name
    if items is not None:
        kwargs["items"] = _pronunciation_dict_items_for_sdk(items)
    return client.pronunciation_dicts.update(dict_id, **kwargs).model_dump(mode="json")


@mcp.tool(
    annotations=_destructive_tool("Delete pronunciation dictionary"),
    description="""
        Permanently delete a pronunciation dictionary.
        """)
def delete_pronunciation_dict(
    dict_id: typing.Annotated[
        str,
        Field(description="Pronunciation dictionary ID to delete."),
    ],
) -> DeletePronunciationDictResult:
    client.pronunciation_dicts.delete(dict_id)
    return DeletePronunciationDictResult(success=True)


@mcp.prompt(
    title="Generate and transcribe",
    description="Synthesize text with a Cartesia voice, then transcribe it back to check the output.",
)
def generate_and_transcribe(text: str, voice: str = "") -> str:
    voice_step = (
        f"Use `list_voices` with q={voice!r} to pick a voice."
        if voice
        else "Use `list_voices` to pick a suitable voice."
    )
    return (
        f"{voice_step}\n"
        f"Call `text_to_speech` with that voice_id, transcript={text!r}, and a wav output_format.\n"
        "Pass the returned `file_id` to `speech_to_text`, then compare the transcript to the "
        "input text and report any differences."
    )


@mcp.prompt(
    title="Clone and localize a voice",
    description="Clone a voice from an audio clip, then localize it to another language.",
)
def clone_and_localize(file_id: str, name: str, target_language: str) -> str:
    return (
        f"Call `clone_voice` with file_id={file_id!r}, name={name!r}, and the clip's language.\n"
        "Call `list_accents` and choose an accent `id` for "
        f"{target_language!r}.\n"
        f"Call `localize_voice` on the new voice with language={target_language!r} and that "
        "accent, then generate a short sample with `text_to_speech` in the target language."
    )


_AGENT_USE_CASE_NOTES = """\
Notes for common agents:
- Inbound support or receptionist: greet with the business name, answer from the facts \
given, collect name and callback number, and enable `system_tools.transfer_to_number` \
for a human handoff.
- Restaurant or order taking: confirm each item, size, and quantity, read the full order \
back, and give a pickup time.
- Outbound sales or SDR: open with who is calling and why in one sentence, qualify with a \
few questions, and handle "not interested" politely. Put the lead's details in \
`{{variables}}`.
- Calling a business on the user's behalf: state the goal, enable \
`system_tools.send_dtmf` to navigate phone menus, and \
`system_tools.voicemail_detection` to hang up on voicemail.
- Interview, sales, or language practice: stay in character as the counterpart, keep \
turns short, and give feedback only when the user asks or the session ends.
- Companion or tutor: be warm, remember what the caller said earlier in the call, and \
ask one question at a time.
"""


@mcp.prompt(
    title="Create a voice agent",
    description="Build a Managed Agent from a plain-language description and share a link to try it.",
)
def create_voice_agent(description: str) -> str:
    return (
        f"Build a Cartesia Managed Agent for: {description!r}.\n"
        "1. Ask at most two questions if a key detail is missing, such as the business "
        "name, the facts the agent must know, or when it should transfer or hang up.\n"
        "2. Call `list_agent_models` and pick a model id. Call `list_voices` with a query "
        "that matches the persona and language, and pick a voice.\n"
        "3. Write `config.instructions` as a spoken-word system prompt: role, goal, tone, "
        "the steps of the conversation, what to collect, and when to end the call. Keep "
        "replies short and avoid formatting the caller cannot hear. Write a one-sentence "
        "`config.initial_message`.\n"
        "4. Use `{{variable}}` placeholders for anything that changes per caller and set "
        "test values in `config.dynamic_variable_placeholders`.\n"
        "5. If the agent must look something up or take an action, call "
        "`create_agent_tool` and put the returned id in `config.tools`. Ending, "
        "transferring, DTMF, and voicemail detection are `config.system_tools`.\n"
        "If it must answer from the user's documents, call `create_knowledge_folder` and "
        "`create_knowledge_documents`, then set `config.knowledge_base_folders`.\n"
        "6. Call `create_agent`, then give the user the `playground_url` to talk to it.\n"
        "7. After a test call, use `list_agent_calls` and `get_agent_call` to review the "
        "transcript, and refine the agent with `update_agent`.\n\n" + _AGENT_USE_CASE_NOTES
    )


@mcp.prompt(
    title="Debug a voice agent call",
    description="Find why a Managed Agent call went wrong and propose a config fix.",
)
def debug_agent_call(agent_id: str, call_id: str = "") -> str:
    call_step = (
        f"Call `get_agent_call` with call_id={call_id!r}."
        if call_id
        else f"Call `list_agent_calls` with agent_id={agent_id!r}, pick the call the user "
        "means (or the latest failed one), and call `get_agent_call` on it."
    )
    return (
        f"{call_step}\n"
        "Check `status`, `end_reason`, and `error_message`, then read the turns for "
        "misunderstandings, interruptions, failed tool calls, and slow `latency_ms`.\n"
        f"Call `get_agent_version` with agent_id={agent_id!r} and the call's "
        "`agent_version_id` to read the config that ran.\n"
        "Explain the cause, then propose the smallest config change. Apply it with "
        "`update_agent` only after the user agrees."
    )


def main():
    parser = argparse.ArgumentParser(description="Cartesia MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="streamable-http" if _is_hosted else "stdio",
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        start_output_directory_cleanup(OUTPUT_DIRECTORY)
        run_hosted(mcp)
        return

    if not CARTESIA_API_KEY:
        raise ValueError("CARTESIA_API_KEY is required for stdio transport")
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
