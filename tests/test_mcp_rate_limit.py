"""Tests for hosted /mcp rate limiting."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.mcp_http import mcp_rate_limit_bucket
from cartesia_mcp.mcp_rate_limit import (
    MCP_INITIALIZE_IP_RATE_LIMIT,
    MCP_INITIALIZE_RATE_LIMIT,
    MCP_IP_RATE_LIMIT,
    MCP_RATE_LIMIT,
    McpRateLimitMiddleware,
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


def _existing_session_headers(**extra: str) -> dict[str, str]:
    return {"mcp-session-id": "existing-session", **extra}


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
            headers=_existing_session_headers(
                authorization="Bearer tok-a",
                **{"x-forwarded-for": "198.51.100.2"},
            ),
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert response.status_code == 200


def test_mcp_rate_limit_blocks_over_cap():
    _reset_store()
    client = _client()
    headers = _existing_session_headers(
        authorization="Bearer tok-b",
        **{"x-forwarded-for": "198.51.100.3"},
    )
    for _ in range(MCP_RATE_LIMIT):
        assert (
            client.post(
                "/mcp",
                headers=headers,
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            ).status_code
            == 200
        )

    blocked = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "too_many_requests"
    assert blocked.headers["retry-after"] == "10"

    other = client.post(
        "/mcp",
        headers=_existing_session_headers(
            authorization="Bearer tok-c",
            **{"x-forwarded-for": "198.51.100.3"},
        ),
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    assert other.status_code == 200


def test_mcp_rate_limit_ip_bucket_applies_with_bearer():
    _reset_store()
    client = _client()
    shared_ip = "198.51.100.44"
    for i in range(MCP_IP_RATE_LIMIT):
        response = client.post(
            "/mcp",
            headers=_existing_session_headers(
                authorization=f"Bearer tok-{i}",
                **{"x-forwarded-for": shared_ip},
            ),
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert response.status_code == 200

    blocked = client.post(
        "/mcp",
        headers=_existing_session_headers(
            authorization="Bearer tok-overflow",
            **{"x-forwarded-for": shared_ip},
        ),
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    assert blocked.status_code == 429
    assert "IP" in blocked.json()["error_description"]


def test_mcp_initialize_rate_limit_blocks_handshake_storm():
    _reset_store()
    client = _client()
    headers = {
        "authorization": "Bearer init-storm",
        "x-forwarded-for": "198.51.100.55",
    }
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    for _ in range(MCP_INITIALIZE_RATE_LIMIT):
        assert client.post("/mcp", headers=headers, json=payload).status_code == 200

    blocked = client.post("/mcp", headers=headers, json=payload)
    assert blocked.status_code == 429
    assert "session creation" in blocked.json()["error_description"]


def test_mcp_session_creation_limit_applies_without_initialize_method():
    _reset_store()
    client = _client()
    headers = {
        "authorization": "Bearer mint-storm",
        "x-forwarded-for": "198.51.100.77",
    }
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    for _ in range(MCP_INITIALIZE_RATE_LIMIT):
        assert client.post("/mcp", headers=headers, json=payload).status_code == 200

    blocked = client.post("/mcp", headers=headers, json=payload)
    assert blocked.status_code == 429
    assert "session creation" in blocked.json()["error_description"]


def test_mcp_session_creation_limit_skips_existing_session():
    _reset_store()
    client = _client()
    headers = _existing_session_headers(
        authorization="Bearer mint-storm",
        **{"x-forwarded-for": "198.51.100.78"},
    )
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    for _ in range(MCP_INITIALIZE_RATE_LIMIT + 3):
        assert client.post("/mcp", headers=headers, json=payload).status_code == 200


def test_mcp_unauthenticated_session_creation_uses_single_bucket():
    _reset_store()
    client = _client()
    headers = {"x-forwarded-for": "198.51.100.88"}
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    for _ in range(MCP_INITIALIZE_RATE_LIMIT):
        assert client.post("/mcp", headers=headers, json=payload).status_code == 200

    blocked = client.post("/mcp", headers=headers, json=payload)
    assert blocked.status_code == 429
    assert "session creation" in blocked.json()["error_description"]


def test_mcp_initialize_ip_rate_limit_blocks_shared_egress():
    _reset_store()
    client = _client()
    payload = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    for i in range(MCP_INITIALIZE_IP_RATE_LIMIT):
        response = client.post(
            "/mcp",
            headers={
                "authorization": f"Bearer init-key-{i}",
                "x-forwarded-for": "198.51.100.66",
            },
            json=payload,
        )
        assert response.status_code == 200

    blocked = client.post(
        "/mcp",
        headers={
            "authorization": "Bearer init-key-overflow",
            "x-forwarded-for": "198.51.100.66",
        },
        json=payload,
    )
    assert blocked.status_code == 429
    assert "IP" in blocked.json()["error_description"]


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
