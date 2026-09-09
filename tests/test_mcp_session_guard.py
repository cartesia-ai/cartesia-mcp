"""Tests for hosted MCP session cap middleware."""

import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.hosted import health
from cartesia_mcp.mcp_session_guard import (
    MCP_MAX_CONCURRENT_SESSIONS,
    McpSessionCapMiddleware,
    bound_session_count,
    configure_hosted_session_manager,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


class _FakeServer:
    pass


class _FakeTransport:
    def __init__(self) -> None:
        self.terminated = False

    async def terminate(self) -> None:
        self.terminated = True


async def _ok_mcp(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _session_manager(*, active: int) -> StreamableHTTPSessionManager:
    manager = StreamableHTTPSessionManager(_FakeServer())
    manager._server_instances = {f"s{i}": _FakeTransport() for i in range(active)}
    manager._session_owners = {f"s{i}": object() for i in range(active)}
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


def test_session_cap_evicts_oldest_at_limit(caplog):
    manager = _session_manager(active=MCP_MAX_CONCURRENT_SESSIONS)
    oldest = manager._server_instances["s0"]
    with caplog.at_level(logging.WARNING, logger="cartesia_mcp.mcp"):
        response = _client(manager).post(
            "/mcp", json={"jsonrpc": "2.0", "method": "initialize"}
        )
    assert response.status_code == 200
    assert oldest.terminated
    assert "s0" not in manager._server_instances
    assert "s0" not in manager._session_owners
    assert any("mcp_session_evicted" in rec.getMessage() for rec in caplog.records)


def test_session_cap_evicts_on_get_without_session():
    manager = _session_manager(active=MCP_MAX_CONCURRENT_SESSIONS)
    oldest = manager._server_instances["s0"]
    response = _client(manager).get("/mcp")
    assert response.status_code == 200
    assert oldest.terminated


def test_session_cap_allows_existing_session_when_at_limit():
    manager = _session_manager(active=MCP_MAX_CONCURRENT_SESSIONS)
    response = _client(manager).post(
        "/mcp",
        headers={"mcp-session-id": "existing-session"},
        json={"jsonrpc": "2.0", "method": "tools/list"},
    )
    assert response.status_code == 200
    assert not any(
        transport.terminated for transport in manager._server_instances.values()
    )


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
