"""Tests for hosted MCP session cap middleware."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.mcp_session_guard import (
    MCP_MAX_CONCURRENT_SESSIONS,
    McpSessionCapMiddleware,
    configure_hosted_session_manager,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


class _FakeServer:
    pass


async def _ok_mcp(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _session_manager(*, active: int) -> StreamableHTTPSessionManager:
    manager = StreamableHTTPSessionManager(_FakeServer())
    manager._server_instances = {f"s{i}": object() for i in range(active)}
    return manager


def _client(session_manager: StreamableHTTPSessionManager) -> TestClient:
    app = Starlette(routes=[Route("/mcp", endpoint=_ok_mcp, methods=["POST"])])
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


def test_session_cap_allows_new_session_under_limit():
    client = _client(_session_manager(active=MCP_MAX_CONCURRENT_SESSIONS - 1))
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "initialize"})
    assert response.status_code == 200


def test_session_cap_blocks_new_session_at_limit():
    client = _client(_session_manager(active=MCP_MAX_CONCURRENT_SESSIONS))
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "initialize"})
    assert response.status_code == 503
    assert response.json()["error"] == "service_unavailable"
    assert response.headers["retry-after"] == "30"


def test_session_cap_allows_existing_session_when_at_limit():
    client = _client(_session_manager(active=MCP_MAX_CONCURRENT_SESSIONS))
    response = client.post(
        "/mcp",
        headers={"mcp-session-id": "existing-session"},
        json={"jsonrpc": "2.0", "method": "tools/list"},
    )
    assert response.status_code == 200
