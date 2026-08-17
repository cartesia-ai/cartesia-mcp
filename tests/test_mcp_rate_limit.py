"""Tests for hosted /mcp rate limiting."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.mcp_rate_limit import (
    MCP_RATE_LIMIT,
    McpRateLimitMiddleware,
    mcp_rate_limit_bucket,
)
from cartesia_mcp.oauth_store import MemoryBackend, oauth_store


def _reset_store() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


async def _ok_mcp(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _client() -> TestClient:
    app = Starlette(
        routes=[
            Route("/mcp", endpoint=_ok_mcp, methods=["GET", "POST"]),
            Route("/health", endpoint=_ok_mcp, methods=["GET"]),
        ]
    )
    app.add_middleware(McpRateLimitMiddleware)
    return TestClient(app)


def test_mcp_rate_limit_bucket_prefers_bearer_hash():
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [
            (b"authorization", b"Bearer secret-token"),
            (b"x-forwarded-for", b"203.0.113.9"),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    bucket = mcp_rate_limit_bucket(Request(scope))
    assert bucket.startswith("tok:")
    assert "secret-token" not in bucket
    assert "203.0.113.9" not in bucket


def test_mcp_rate_limit_allows_under_cap():
    _reset_store()
    client = _client()
    for _ in range(MCP_RATE_LIMIT):
        response = client.post(
            "/mcp",
            headers={
                "authorization": "Bearer tok-a",
                "x-forwarded-for": "198.51.100.2",
            },
            json={},
        )
        assert response.status_code == 200


def test_mcp_rate_limit_blocks_over_cap():
    _reset_store()
    client = _client()
    headers = {
        "authorization": "Bearer tok-b",
        "x-forwarded-for": "198.51.100.3",
    }
    for _ in range(MCP_RATE_LIMIT):
        assert client.post("/mcp", headers=headers, json={}).status_code == 200

    blocked = client.post("/mcp", headers=headers, json={})
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "too_many_requests"
    assert blocked.headers["retry-after"] == "10"

    other = client.post(
        "/mcp",
        headers={
            "authorization": "Bearer tok-c",
            "x-forwarded-for": "198.51.100.3",
        },
        json={},
    )
    assert other.status_code == 200


def test_mcp_rate_limit_unauthenticated_keys_by_ip():
    _reset_store()
    client = _client()
    shared = {"x-forwarded-for": "198.51.100.6"}
    for _ in range(MCP_RATE_LIMIT):
        assert client.get("/mcp", headers=shared).status_code == 200

    assert client.get("/mcp", headers=shared).status_code == 429
    other = client.get("/mcp", headers={"x-forwarded-for": "198.51.100.7"})
    assert other.status_code == 200


def test_mcp_rate_limit_skips_health():
    _reset_store()
    client = _client()
    headers = {"x-forwarded-for": "198.51.100.5"}
    for _ in range(MCP_RATE_LIMIT + 5):
        assert client.get("/health", headers=headers).status_code == 200
