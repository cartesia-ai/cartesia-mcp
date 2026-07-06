import typing


class DeleteVoiceResult(typing.TypedDict):
    success: bool


class GeneratedAudioResult(typing.TypedDict, total=False):
    """TTS with save=true returns file_id and download_url; voice_change is local-only."""

    file_id: str
    download_url: str
    file_path: str


class DownloadedFileResult(typing.TypedDict):
    file_id: str
    download_url: str
    file_path: str
    filename: str


class ListVoicesResult(typing.TypedDict, total=False):
    data: typing.List[typing.Any]
    has_more: bool
    next_page: str
