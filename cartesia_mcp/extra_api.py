"""
HTTP helpers for Cartesia endpoints not generated on the Python SDK.

`get_usage_credits` must be called with a client authenticated using an admin API key
(`CARTESIA_ADMIN_API_KEY`); standard API keys are rejected on `/usage/*`.
"""

from __future__ import annotations

import typing

from cartesia import Cartesia

UsageInterval = typing.Literal["day", "week", "month"]


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
