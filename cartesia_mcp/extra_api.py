"""
HTTP helpers for Cartesia endpoints not generated on the Fern v2 Python SDK.

The pinned `cartesia` 2.x client exposes tts, stt, voices, and voice_changer
only — not pronunciation dictionaries or usage/credits. These thin wrappers call the
same httpx stack as the SDK (shared auth, base URL, and Cartesia-Version header).

`get_usage_credits` must be called with an HTTP client authenticated using an admin API key
(`CARTESIA_ADMIN_API_KEY`); standard API keys are rejected on `/usage/*`.
"""

from __future__ import annotations

import typing

from cartesia.core.http_client import HttpClient

UsageInterval = typing.Literal["day", "week", "month"]


def _json_response(response) -> dict[str, typing.Any]:
    response.raise_for_status()
    return response.json()


def get_usage_credits(
    http: HttpClient,
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
    return _json_response(http.request("usage/credits", method="GET", params=params))


def list_pronunciation_dicts(
    http: HttpClient,
    *,
    limit: typing.Optional[int] = None,
    starting_after: typing.Optional[str] = None,
    ending_before: typing.Optional[str] = None,
) -> dict[str, typing.Any]:
    params: dict[str, typing.Any] = {}
    if limit is not None:
        params["limit"] = limit
    if starting_after is not None:
        params["starting_after"] = starting_after
    if ending_before is not None:
        params["ending_before"] = ending_before
    return _json_response(
        http.request("pronunciation-dicts", method="GET", params=params)
    )


def create_pronunciation_dict(
    http: HttpClient,
    *,
    name: str,
    items: typing.Optional[typing.Sequence[dict[str, str]]] = None,
) -> dict[str, typing.Any]:
    body: dict[str, typing.Any] = {"name": name}
    if items is not None:
        body["items"] = list(items)
    return _json_response(
        http.request("pronunciation-dicts", method="POST", json=body)
    )


def get_pronunciation_dict(http: HttpClient, dict_id: str) -> dict[str, typing.Any]:
    return _json_response(
        http.request(f"pronunciation-dicts/{dict_id}", method="GET")
    )


def update_pronunciation_dict(
    http: HttpClient,
    dict_id: str,
    *,
    name: typing.Optional[str] = None,
    items: typing.Optional[typing.Sequence[dict[str, str]]] = None,
) -> dict[str, typing.Any]:
    body: dict[str, typing.Any] = {}
    if name is not None:
        body["name"] = name
    if items is not None:
        body["items"] = list(items)
    if not body:
        raise ValueError("At least one of `name` or `items` must be provided.")
    return _json_response(
        http.request(f"pronunciation-dicts/{dict_id}", method="PATCH", json=body)
    )


def delete_pronunciation_dict(http: HttpClient, dict_id: str) -> None:
    http.request(f"pronunciation-dicts/{dict_id}", method="DELETE").raise_for_status()
