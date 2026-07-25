"""Tests for /register IP rate limiting."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.oauth_store import MemoryBackend, oauth_store
from cartesia_mcp.register_rate_limit import (
    REGISTER_RATE_LIMIT,
    RegisterRateLimitMiddleware,
    client_ip,
)


def _reset_store() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


async def _ok_register(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _client() -> TestClient:
    app = Starlette(routes=[Route("/register", endpoint=_ok_register, methods=["POST"])])
    app.add_middleware(RegisterRateLimitMiddleware)
    return TestClient(app)


def test_client_ip_prefers_x_forwarded_for():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.1")],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)
    assert client_ip(request) == "203.0.113.9"


def test_register_rate_limit_allows_under_cap():
    _reset_store()
    client = _client()
    for _ in range(REGISTER_RATE_LIMIT):
        response = client.post(
            "/register",
            headers={"x-forwarded-for": "198.51.100.2"},
            json={},
        )
        assert response.status_code == 200


def test_register_rate_limit_blocks_over_cap():
    _reset_store()
    client = _client()
    for _ in range(REGISTER_RATE_LIMIT):
        assert (
            client.post(
                "/register",
                headers={"x-forwarded-for": "198.51.100.3"},
                json={},
            ).status_code
            == 200
        )

    blocked = client.post(
        "/register",
        headers={"x-forwarded-for": "198.51.100.3"},
        json={},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "too_many_requests"
    assert blocked.headers["retry-after"]

    # Different IP is unaffected.
    other = client.post(
        "/register",
        headers={"x-forwarded-for": "198.51.100.4"},
        json={},
    )
    assert other.status_code == 200
