"""Tests for hosted MCP session cap middleware."""

import hashlib
import json
import logging
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.hosted import health
from cartesia_mcp.mcp_session_guard import (
    MCP_MAX_CONCURRENT_SESSIONS,
    MCP_SESSION_IDLE_TIMEOUT_SECONDS,
    McpSessionCapMiddleware,
    bound_session_count,
    configure_hosted_session_manager,
)
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

CREATED_SESSION_ID = "created-session"


class _FakeServer:
    pass


class _FakeTransport:
    def __init__(self) -> None:
        self.terminated = False

    async def terminate(self) -> None:
        self.terminated = True


async def _ok_mcp(request: Request) -> JSONResponse:
    headers = {}
    if request.headers.get(MCP_SESSION_ID_HEADER) is None:
        headers[MCP_SESSION_ID_HEADER] = CREATED_SESSION_ID
    return JSONResponse({"ok": True}, headers=headers)


def _token_bucket(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"tok:{digest}"


def _session_manager(
    *,
    active: int,
    owners: dict[str, str] | None = None,
    last_seen: dict[str, float] | None = None,
) -> StreamableHTTPSessionManager:
    now = time.monotonic()
    manager = StreamableHTTPSessionManager(_FakeServer())
    manager._server_instances = {f"s{i}": _FakeTransport() for i in range(active)}
    manager._session_owners = (
        owners
        if owners is not None
        else {f"s{i}": f"tok:other-{i}" for i in range(active)}
    )
    manager._session_last_seen = (
        last_seen
        if last_seen is not None
        else {f"s{i}": now for i in range(active)}
    )
    return manager


def _client(session_manager: StreamableHTTPSessionManager) -> TestClient:
    app = Starlette(
        routes=[Route("/mcp", endpoint=_ok_mcp, methods=["GET", "POST"])]
    )
    app.add_middleware(
        McpSessionCapMiddleware,
        session_manager=session_manager,
    )
    return TestClient(app)


def _eviction_payloads(caplog) -> list[dict]:
    payloads = []
    for rec in caplog.records:
        message = rec.getMessage()
        if "mcp_session_evicted" not in message:
            continue
        payloads.append(json.loads(message))
    return payloads


def test_configure_hosted_session_manager_sets_idle_timeout():
    manager = _session_manager(active=0)
    assert manager.session_idle_timeout is None
    configure_hosted_session_manager(manager)
    assert manager.session_idle_timeout == 300
    assert bound_session_count() == 0


def test_session_cap_allows_new_session_under_limit():
    manager = _session_manager(active=MCP_MAX_CONCURRENT_SESSIONS - 1)
    response = _client(manager).post(
        "/mcp", json={"jsonrpc": "2.0", "method": "initialize"}
    )
    assert response.status_code == 200
    assert not next(iter(manager._server_instances.values())).terminated


def test_session_cap_same_bucket_replaces_owner_not_fifo(caplog):
    caller = "caller-token"
    owners = {f"s{i}": f"tok:other-{i}" for i in range(MCP_MAX_CONCURRENT_SESSIONS)}
    owners["s1"] = _token_bucket(caller)
    manager = _session_manager(
        active=MCP_MAX_CONCURRENT_SESSIONS,
        owners=owners,
    )
    fifo = manager._server_instances["s0"]
    owned = manager._server_instances["s1"]
    with caplog.at_level(logging.WARNING, logger="cartesia_mcp.mcp"):
        response = _client(manager).post(
            "/mcp",
            headers={"authorization": f"Bearer {caller}"},
            json={"jsonrpc": "2.0", "method": "initialize"},
        )
    assert response.status_code == 200
    assert not fifo.terminated
    assert "s0" in manager._server_instances
    assert owned.terminated
    assert "s1" not in manager._server_instances
    assert "s1" not in manager._session_owners
    assert "s1" not in manager._session_last_seen
    payloads = _eviction_payloads(caplog)
    assert len(payloads) == 1
    assert payloads[0]["evicted"] == "s1"
    assert payloads[0]["reason"] == "replace"


def test_session_cap_evicts_idle_before_recently_used(caplog):
    now = time.monotonic()
    last_seen = {f"s{i}": now for i in range(MCP_MAX_CONCURRENT_SESSIONS)}
    last_seen["s1"] = now - MCP_SESSION_IDLE_TIMEOUT_SECONDS - 1
    manager = _session_manager(
        active=MCP_MAX_CONCURRENT_SESSIONS,
        last_seen=last_seen,
    )
    hot = manager._server_instances["s0"]
    idle = manager._server_instances["s1"]
    with caplog.at_level(logging.WARNING, logger="cartesia_mcp.mcp"):
        response = _client(manager).post(
            "/mcp", json={"jsonrpc": "2.0", "method": "initialize"}
        )
    assert response.status_code == 200
    assert not hot.terminated
    assert "s0" in manager._server_instances
    assert idle.terminated
    assert "s1" not in manager._server_instances
    assert "s1" not in manager._session_owners
    payloads = _eviction_payloads(caplog)
    assert len(payloads) == 1
    assert payloads[0]["evicted"] == "s1"
    assert payloads[0]["reason"] == "idle"


def test_session_cap_all_hot_returns_503_and_terminates_nobody():
    manager = _session_manager(active=MCP_MAX_CONCURRENT_SESSIONS)
    client = _client(manager)
    post = client.post("/mcp", json={"jsonrpc": "2.0", "method": "initialize"})
    get = client.get("/mcp")
    assert post.status_code == 503
    assert get.status_code == 503
    assert post.headers["retry-after"] == "30"
    assert get.headers["retry-after"] == "30"
    assert post.json()["error"] == "service_unavailable"
    assert len(manager._server_instances) == MCP_MAX_CONCURRENT_SESSIONS
    assert not any(
        transport.terminated for transport in manager._server_instances.values()
    )


def test_session_cap_existing_session_at_cap_refreshes_last_seen():
    now = time.monotonic()
    last_seen = {f"s{i}": now - 10 for i in range(MCP_MAX_CONCURRENT_SESSIONS)}
    manager = _session_manager(
        active=MCP_MAX_CONCURRENT_SESSIONS,
        last_seen=last_seen,
    )
    before = manager._session_last_seen["s0"]
    response = _client(manager).post(
        "/mcp",
        headers={MCP_SESSION_ID_HEADER: "s0"},
        json={"jsonrpc": "2.0", "method": "tools/list"},
    )
    assert response.status_code == 200
    assert manager._session_last_seen["s0"] > before
    assert len(manager._server_instances) == MCP_MAX_CONCURRENT_SESSIONS
    assert not any(
        transport.terminated for transport in manager._server_instances.values()
    )


def test_session_owners_written_on_create_and_cleaned_on_evict(caplog):
    caller = "create-token"
    manager = _session_manager(active=0)
    create = _client(manager).post(
        "/mcp",
        headers={"authorization": f"Bearer {caller}"},
        json={"jsonrpc": "2.0", "method": "initialize"},
    )
    assert create.status_code == 200
    assert manager._session_owners[CREATED_SESSION_ID] == _token_bucket(caller)
    assert CREATED_SESSION_ID in manager._session_last_seen

    now = time.monotonic()
    manager._server_instances = {
        f"s{i}": _FakeTransport() for i in range(MCP_MAX_CONCURRENT_SESSIONS)
    }
    manager._session_owners = {
        f"s{i}": f"tok:other-{i}" for i in range(MCP_MAX_CONCURRENT_SESSIONS)
    }
    manager._session_owners["s3"] = _token_bucket(caller)
    manager._session_last_seen = {
        f"s{i}": now for i in range(MCP_MAX_CONCURRENT_SESSIONS)
    }
    with caplog.at_level(logging.WARNING, logger="cartesia_mcp.mcp"):
        replace = _client(manager).post(
            "/mcp",
            headers={"authorization": f"Bearer {caller}"},
            json={"jsonrpc": "2.0", "method": "initialize"},
        )
    assert replace.status_code == 200
    assert "s3" not in manager._session_owners
    assert "s3" not in manager._session_last_seen
    assert manager._session_owners[CREATED_SESSION_ID] == _token_bucket(caller)
    assert _eviction_payloads(caplog)[0]["reason"] == "replace"


def test_health_includes_session_count():
    manager = _session_manager(active=3)
    configure_hosted_session_manager(manager)
    app = Starlette(routes=[Route("/health", endpoint=health, methods=["GET"])])
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "sessions": 3,
        "session_cap": MCP_MAX_CONCURRENT_SESSIONS,
    }
