import typing


class PronunciationDictItemParams(typing.TypedDict):
    text: str
    pronunciation: str


class ListPronunciationDictsResult(typing.TypedDict, total=False):
    data: typing.List[typing.Any]
    has_more: bool
    next_page: str


class DeletePronunciationDictResult(typing.TypedDict):
    success: bool
