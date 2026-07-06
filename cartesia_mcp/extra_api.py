"""
HTTP helpers for Cartesia endpoints not generated on the Python SDK.

`get_usage_credits` must be called with a client authenticated using an admin API key
(`CARTESIA_ADMIN_API_KEY`); standard API keys are rejected on `/usage/*`.

Files helpers call the Cartesia files service (override with `CARTESIA_FILES_BASE_URL`).
"""

from __future__ import annotations

import os
import typing
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from cartesia import Cartesia

from cartesia_mcp.config import env_or_none

UsageInterval = typing.Literal["day", "week", "month"]
DownloadFormat = typing.Literal["playback"]

DEFAULT_FILES_BASE_URL = "https://files.cartesia.ai"
DEFAULT_DOWNLOAD_LINK_LIFETIME_HOURS = 24
CARTESIA_FILE_ID_HEADER = "cartesia-file-id"


def files_base_url() -> str:
    return env_or_none("CARTESIA_FILES_BASE_URL", os.environ) or DEFAULT_FILES_BASE_URL


def _files_url(path: str) -> str:
    return f"{files_base_url().rstrip('/')}{path}"


def file_id_from_response_headers(headers: typing.Mapping[str, str]) -> typing.Optional[str]:
    for key, value in headers.items():
        if key.lower() == CARTESIA_FILE_ID_HEADER:
            stripped = value.strip()
            return stripped or None
    return None


def with_download_format(url: str, format: typing.Optional[DownloadFormat]) -> str:
    if format is None:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["format"] = format
    return urlunparse(parsed._replace(query=urlencode(query)))


def get_usage_credits(
    client: Cartesia,
    *,
    start_ts: typing.Optional[str] = None,
    end_ts: typing.Optional[str] = None,
    interval: typing.Optional[UsageInterval] = None,
    api_key_id: typing.Optional[str] = None,
) -> dict[str, typing.Any]:
    params: dict[str, str] = {}
    if start_ts is not None:
        params["start_ts"] = start_ts
    if end_ts is not None:
        params["end_ts"] = end_ts
    if interval is not None:
        params["interval"] = interval
    if api_key_id is not None:
        params["api_key_id"] = api_key_id
    return client.get(
        "/usage/credits",
        cast_to=dict[str, typing.Any],
        options={"params": params},
    )


def get_file_info(client: Cartesia, file_id: str) -> dict[str, typing.Any]:
    return client.get(
        _files_url(f"/files/{file_id}/info"),
        cast_to=dict[str, typing.Any],
    )


def download_file_bytes(
    client: Cartesia,
    file_id: str,
    *,
    format: typing.Optional[DownloadFormat] = None,
) -> bytes:
    params: dict[str, str] = {}
    if format is not None:
        params["format"] = format
    return client.get(
        _files_url(f"/files/{file_id}/download"),
        cast_to=bytes,
        options={"params": params} if params else None,
    )


def create_file_download_link(
    client: Cartesia,
    file_id: str,
    *,
    lifetime_hours: int = DEFAULT_DOWNLOAD_LINK_LIFETIME_HOURS,
) -> str:
    payload = client.post(
        _files_url("/links"),
        cast_to=dict[str, typing.Any],
        body={"file_id": file_id, "lifetime": f"{lifetime_hours}h"},
    )
    url = payload.get("url")
    if not isinstance(url, str) or not url.strip():
        raise RuntimeError("files API did not return a download link URL")
    return url
