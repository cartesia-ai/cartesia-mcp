import typing


class DeleteVoiceResult(typing.TypedDict):
    success: bool


class GeneratedAudioResult(typing.TypedDict):
    file_path: str


class ListVoicesResult(typing.TypedDict, total=False):
    data: typing.List[typing.Any]
    has_more: bool
    next_page: str


