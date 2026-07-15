import typing


class PronunciationDictItemParams(typing.TypedDict):
    text: str
    pronunciation: str


class ListPronunciationDictsResult(typing.TypedDict):
    """Paginated pronunciation-dict list.

    `next_page` must be nullable: FastMCP dumps unset optional TypedDict fields as
    ``None``, and clients validate structured output against this schema.
    """

    data: typing.List[typing.Any]
    has_more: bool
    next_page: typing.NotRequired[str | None]


class DeletePronunciationDictResult(typing.TypedDict):
    success: bool
