"""HTTP helpers for Cartesia APIs not exposed on the Fern v2 SDK client."""

from __future__ import annotations

import os
import typing

import httpx

CARTESIA_API_BASE = os.getenv("CARTESIA_API_BASE", "https://api.cartesia.ai")
CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2024-11-13")

UsageInterval = typing.Literal["day", "week", "month"]


class CartesiaRestClient:
    def __init__(self, api_key: str) -> None:
        self._client = httpx.Client(
            base_url=CARTESIA_API_BASE,
            headers={
                "X-API-Key": api_key,
                "Cartesia-Version": CARTESIA_VERSION,
            },
            timeout=60.0,
        )

    def get_usage_credits(
        self,
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
        response = self._client.get("/usage/credits", params=params)
        response.raise_for_status()
        return response.json()

    def list_pronunciation_dicts(
        self,
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
        response = self._client.get("/pronunciation-dicts/", params=params)
        response.raise_for_status()
        return response.json()

    def create_pronunciation_dict(
        self,
        *,
        name: str,
        items: typing.Optional[typing.Sequence[dict[str, str]]] = None,
    ) -> dict[str, typing.Any]:
        body: dict[str, typing.Any] = {"name": name}
        if items is not None:
            body["items"] = list(items)
        response = self._client.post("/pronunciation-dicts/", json=body)
        response.raise_for_status()
        return response.json()

    def get_pronunciation_dict(self, dict_id: str) -> dict[str, typing.Any]:
        response = self._client.get(f"/pronunciation-dicts/{dict_id}")
        response.raise_for_status()
        return response.json()

    def update_pronunciation_dict(
        self,
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
        response = self._client.patch(f"/pronunciation-dicts/{dict_id}", json=body)
        response.raise_for_status()
        return response.json()

    def delete_pronunciation_dict(self, dict_id: str) -> None:
        response = self._client.delete(f"/pronunciation-dicts/{dict_id}")
        response.raise_for_status()
