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
UsageCreditsGroupBy = typing.Literal["capability", "model", "voice", "api_key"]
DownloadFormat = typing.Literal["playback"]

DEFAULT_FILES_BASE_URL = "https://files.cartesia.ai"
DEFAULT_DOWNLOAD_LINK_LIFETIME_HOURS = 24
CARTESIA_FILE_ID_HEADER = "cartesia-file-id"
CARTESIA_NOTICE_HEADER = "cartesia-notice"


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


def notice_from_response_headers(headers: typing.Mapping[str, str]) -> typing.Optional[str]:
    """A message from Cartesia about the account, e.g. free credits running low."""
    for key, value in headers.items():
        if key.lower() == CARTESIA_NOTICE_HEADER:
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
    group_by: typing.Optional[UsageCreditsGroupBy] = None,
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
    if group_by is not None:
        params["group_by"] = group_by
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
        options={"params": params},
    )


ModelCapability = typing.Literal["tts", "stt"]


def list_models(
    client: Cartesia,
    *,
    capability: typing.Optional[ModelCapability] = None,
) -> dict[str, typing.Any]:
    """GET /models — public Sonic (TTS) and Ink (STT) catalog."""
    params: dict[str, str] = {}
    if capability is not None:
        params["capability"] = capability
    return client.get(
        "/models",
        cast_to=dict[str, typing.Any],
        options={"params": params},
    )


def list_agent_models(client: Cartesia) -> dict[str, typing.Any]:
    """GET /v1/agents/models — Managed Agents LLM catalog.

    The catalog is small, but a page boundary must not silently truncate IDs
    coding agents use when creating or updating agents: follow next_page until
    the server reports the end.
    """
    models: list[dict[str, typing.Any]] = []
    cursor: typing.Optional[str] = None
    while True:
        params: dict[str, str] = {"limit": "100"}
        if cursor is not None:
            params["starting_after"] = cursor
        page = client.get(
            "/v1/agents/models",
            cast_to=dict[str, typing.Any],
            options={"params": params},
        )
        page_data = page.get("data")
        if isinstance(page_data, list):
            models.extend(item for item in page_data if isinstance(item, dict))
        if not page.get("has_more"):
            break
        next_page = page.get("next_page")
        if not isinstance(next_page, str) or not next_page:
            break
        cursor = next_page
    return {"data": models}


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
