import os
import datetime
import typing
from pathlib import Path
from cartesia_mcp.custom_types import ToolType, ListVoicesResult
from cartesia.core.pagination import SyncPager
from cartesia.core.request_options import RequestOptions
from cartesia.voice_changer.types import OutputFormatContainer
from cartesia.voices.types import Voice

def create_output_file(output_directory: str, tool_type: ToolType,
                       extension: OutputFormatContainer) -> Path:
    dir_path = Path(output_directory)

    dir_path.mkdir(parents=True, exist_ok=True)

    if not os.access(dir_path, os.W_OK):
        raise Exception(
            f"Output directory {dir_path} is not writable")

    return dir_path / f"{tool_type}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.{extension}"


def build_list_voices_request_options(
    request_options: typing.Optional[RequestOptions],
    *,
    language: typing.Optional[str] = None,
    q: typing.Optional[str] = None,
    expand: typing.Optional[typing.Sequence[str]] = None,
) -> typing.Optional[RequestOptions]:
    extra_query: dict[str, typing.Any] = {}
    if language is not None:
        extra_query["language"] = language
    if q is not None:
        extra_query["q"] = q
    if expand:
        extra_query["expand[]"] = list(expand)
    if not extra_query:
        return request_options

    merged: RequestOptions = dict(request_options or {})
    base = dict(merged.get("additional_query_parameters") or {})
    base.update(extra_query)
    merged["additional_query_parameters"] = base
    return merged


def voice_list_page_to_result(pager: SyncPager[Voice]) -> ListVoicesResult:
    data = [voice.model_dump(mode="json") for voice in pager.items]
    result: ListVoicesResult = {"data": data, "has_more": pager.has_next}
    if pager.has_next and data:
        result["next_page"] = data[-1]["id"]
    return result
