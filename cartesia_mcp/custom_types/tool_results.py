import typing


class DeleteVoiceResult(typing.TypedDict):
    success: bool


class DeleteFileResult(typing.TypedDict):
    success: bool


class GeneratedAudioResult(typing.TypedDict):
    file_path: str


class DownloadedFileResult(typing.TypedDict):
    file_path: str
    file_id: str
    filename: str


class ListFilesResult(typing.TypedDict, total=False):
    data: typing.List[typing.Any]
    has_more: bool


class ListVoicesResult(typing.TypedDict, total=False):
    data: typing.List[typing.Any]
    has_more: bool
    next_page: str


