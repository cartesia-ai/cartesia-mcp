"""Pytest setup shared across the test suite."""

from __future__ import annotations

import os
import typing
from collections.abc import Callable, Iterator
from unittest.mock import patch

import httpx
import pytest
from cartesia import Cartesia

# server.py validates keys at import time; unit tests mock HTTP clients instead.
os.environ.setdefault(
    "CARTESIA_API_KEY",
    "sk_car_testId1234567890ab.secretPartHere1234567890abcdefghij",
)


Handler = Callable[[httpx.Request], typing.Any]


class Api:
    """Fake Cartesia API: records requests and answers from a route table."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Handler] = {}

    def on(self, method: str, path: str, body: typing.Any) -> None:
        self.routes[(method, path)] = lambda _request: body

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get((request.method, request.url.raw_path.decode().split("?")[0]))
        if handler is None:
            return httpx.Response(404, json={"error": "not found"})
        body = handler(request)
        return httpx.Response(204) if body is None else httpx.Response(200, json=body)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


@pytest.fixture
def api() -> Iterator[Api]:
    fake = Api()
    sdk = Cartesia(
        api_key="sk_test",
        base_url="https://api.test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(fake._handle)),
    )
    with patch("cartesia_mcp.server.client", sdk):
        yield fake
