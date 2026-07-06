"""
HTTP helpers for Cartesia endpoints not generated on the Python SDK.

`get_usage_credits` must be called with a client authenticated using an admin API key
(`CARTESIA_ADMIN_API_KEY`); standard API keys are rejected on `/usage/*`.

Files helpers call `files.cartesia.ai` (override with `CARTESIA_FILES_BASE_URL`).
"""

from __future__ import annotations

import os
import typing

from cartesia import Cartesia

from cartesia_mcp.config import env_or_none

UsageInterval = typing.Literal["day", "week", "month"]
DownloadFormat = typing.Literal["playback"]
FilePurpose = typing.Literal[
    "agent_background_sound",
    "agent_source_archive",
    "fine_tune",
    "narration_export",
    "original-audio-clip",
    "synthetic-conditioning-audio",
    "tts_generation",
    "voice-clone",
    "voice_sample",
]

DEFAULT_FILES_BASE_URL = "https://files.cartesia.ai"


def files_base_url() -> str:
    return env_or_none("CARTESIA_FILES_BASE_URL", os.environ) or DEFAULT_FILES_BASE_URL


def _files_url(path: str) -> str:
    return f"{files_base_url().rstrip('/')}{path}"


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


def list_files(
    client: Cartesia,
    *,
    limit: typing.Optional[int] = None,
    purpose: typing.Optional[FilePurpose] = None,
    query: typing.Optional[str] = None,
) -> dict[str, typing.Any]:
    params: dict[str, str] = {}
    if limit is not None:
        params["limit"] = str(limit)
    if purpose is not None:
        params["purpose"] = purpose
    if query is not None:
        params["q"] = query
    return client.get(
        _files_url("/files"),
        cast_to=dict[str, typing.Any],
        options={"params": params} if params else None,
    )
