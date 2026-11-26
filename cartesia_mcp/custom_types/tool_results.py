import typing


class DeleteVoiceResult(typing.TypedDict):
    success: bool


class GeneratedAudioResult(typing.TypedDict, total=False):
    """Audio delivery fields for `text_to_speech`.

    Fields are optional because `save=false` is local-only. Optional string
    fields must be nullable: FastMCP dumps unset TypedDict keys as ``None``.

    The request-echo fields (`transcript`, `voice_id`, …) are only returned to
    clients that support MCP Apps; they let the player rebuild the request.
    """

    file_id: str | None
    download_url: str | None
    file_path: str | None
    transcript: str | None
    voice_id: str | None
    model_id: str | None
    language: str | None
    emotion: str | None
    speed: float | None
    volume: float | None
    duration: float | None
    pronunciation_dict_id: str | None
    output_format: dict[str, typing.Any] | None
    cartesia_version: str | None


class DownloadedFileResult(typing.TypedDict):
    """Result of `download_file` / cloud file delivery.

    `download_url` is omitted when link minting fails; it must be nullable so
    FastMCP structured output still validates.
    """

    file_id: str
    file_path: str
    filename: str
    download_url: typing.NotRequired[str | None]


class ListVoicesResult(typing.TypedDict):
    """Paginated voice list returned by `list_voices`.

    `next_page` is omitted by the tool when there is no further page, but FastMCP's
    structured-output dump fills optional TypedDict fields with ``None``. The field
    must therefore be nullable in the JSON Schema or clients reject the last page
    with ``None is not of type 'string'``.
    """

    data: typing.List[typing.Any]
    has_more: bool
    next_page: typing.NotRequired[str | None]
