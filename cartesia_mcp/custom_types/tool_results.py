import typing


class DeleteVoiceResult(typing.TypedDict):
    success: bool


class GeneratedAudioResult(typing.TypedDict, total=False):
    """TTS with save=true returns file_id and usually download_url; voice_change is local-only."""

    file_id: str
    download_url: str
    file_path: str


class DownloadedFileResult(typing.TypedDict, total=False):
    file_id: str
    file_path: str
    filename: str
    download_url: str


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
