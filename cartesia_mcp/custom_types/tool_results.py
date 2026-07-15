import typing


class DeleteVoiceResult(typing.TypedDict):
    success: bool


class GeneratedAudioResult(typing.TypedDict, total=False):
    """Audio delivery fields for `text_to_speech` / `voice_change`.

    Fields are optional because paths differ (`save=false` is local-only;
    `voice_change` never mints cloud links). Optional string fields must be
    nullable: FastMCP dumps unset TypedDict keys as ``None``.
    """

    file_id: str | None
    download_url: str | None
    file_path: str | None


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
