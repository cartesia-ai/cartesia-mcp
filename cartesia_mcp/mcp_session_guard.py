"""Cap concurrent Streamable HTTP MCP sessions on the hosted server."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from cartesia_mcp.mcp_http import is_mcp_path

# Enough for normal OAuth clients; blocks reconnect storms from unbounded growth.
MCP_MAX_CONCURRENT_SESSIONS = 256

# Reclaim idle SSE sessions; SDK default is None (no timeout).
MCP_SESSION_IDLE_TIMEOUT_SECONDS = 300


def active_session_count(session_manager: StreamableHTTPSessionManager) -> int:
    return len(session_manager._server_instances)


def configure_hosted_session_manager(
    session_manager: StreamableHTTPSessionManager,
) -> None:
    session_manager.session_idle_timeout = MCP_SESSION_IDLE_TIMEOUT_SECONDS


class McpSessionCapMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        session_manager: StreamableHTTPSessionManager,
    ) -> None:
        super().__init__(app)
        self._session_manager = session_manager

    async def dispatch(self, request: Request, call_next) -> Response:
        if (
            request.method == "POST"
            and is_mcp_path(request.url.path)
            and request.headers.get(MCP_SESSION_ID_HEADER) is None
            and active_session_count(self._session_manager) >= MCP_MAX_CONCURRENT_SESSIONS
        ):
            return JSONResponse(
                {
                    "error": "service_unavailable",
                    "error_description": "Too many active MCP sessions",
                },
                status_code=503,
                headers={"Retry-After": "30"},
            )
        return await call_next(request)
