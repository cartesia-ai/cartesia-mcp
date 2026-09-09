"""Cap concurrent Streamable HTTP MCP sessions on the hosted server."""

from __future__ import annotations

import json
import logging
import os
import socket
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from cartesia_mcp.mcp_http import is_mcp_path

logger = logging.getLogger("cartesia_mcp.mcp")

# In-memory sessions on one replica. LRU eviction absorbs reconnect storms.
MCP_MAX_CONCURRENT_SESSIONS = 1024

# Reclaim idle SSE sessions; SDK default is None (no timeout).
MCP_SESSION_IDLE_TIMEOUT_SECONDS = 300

_NEW_SESSION_METHODS = frozenset({"GET", "POST"})

_bound_session_manager: StreamableHTTPSessionManager | None = None


def active_session_count(session_manager: StreamableHTTPSessionManager) -> int:
    return len(session_manager._server_instances)


def bound_session_count() -> int:
    if _bound_session_manager is None:
        return 0
    return active_session_count(_bound_session_manager)


def configure_hosted_session_manager(
    session_manager: StreamableHTTPSessionManager,
) -> None:
    global _bound_session_manager
    _bound_session_manager = session_manager
    session_manager.session_idle_timeout = MCP_SESSION_IDLE_TIMEOUT_SECONDS


def _dogstatsd_addr() -> tuple[str, int] | None:
    url = os.environ.get("DD_DOGSTATSD_URL")
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.hostname is None:
        return None
    return parsed.hostname, parsed.port or 8125


def _dogstatsd_tags() -> str:
    tags = ["service:cartesia-mcp"]
    env = os.environ.get("DD_ENV")
    if env:
        tags.append(f"env:{env}")
    return ",".join(tags)


def _dogstatsd_send(metric: str, value: float, kind: str) -> None:
    addr = _dogstatsd_addr()
    if addr is None:
        return
    payload = f"{metric}:{value}|{kind}|#{_dogstatsd_tags()}\n"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.sendto(payload.encode("utf-8"), addr)
        sock.close()
    except OSError:
        return


def report_session_metrics(active: int, *, evicted: int = 0) -> None:
    _dogstatsd_send("mcp.sessions.active", active, "g")
    _dogstatsd_send("mcp.sessions.cap", MCP_MAX_CONCURRENT_SESSIONS, "g")
    if evicted:
        _dogstatsd_send("mcp.sessions.evicted", evicted, "c")


async def evict_oldest_session(
    session_manager: StreamableHTTPSessionManager,
) -> str | None:
    try:
        oldest_id = next(iter(session_manager._server_instances))
    except StopIteration:
        return None
    transport = session_manager._server_instances.pop(oldest_id, None)
    owners = getattr(session_manager, "_session_owners", None)
    if isinstance(owners, dict):
        owners.pop(oldest_id, None)
    terminate = getattr(transport, "terminate", None)
    if callable(terminate):
        await terminate()
    return oldest_id


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
            request.method in _NEW_SESSION_METHODS
            and is_mcp_path(request.url.path)
            and request.headers.get(MCP_SESSION_ID_HEADER) is None
        ):
            active = active_session_count(self._session_manager)
            report_session_metrics(active)
            if active >= MCP_MAX_CONCURRENT_SESSIONS:
                evicted = await evict_oldest_session(self._session_manager)
                if evicted is None:
                    return JSONResponse(
                        {
                            "error": "service_unavailable",
                            "error_description": "Too many active MCP sessions",
                        },
                        status_code=503,
                        headers={"Retry-After": "30"},
                    )
                logger.warning(
                    json.dumps(
                        {
                            "event": "mcp_session_evicted",
                            "active": active,
                            "cap": MCP_MAX_CONCURRENT_SESSIONS,
                            "evicted": evicted,
                        },
                        separators=(",", ":"),
                    )
                )
                report_session_metrics(
                    active_session_count(self._session_manager),
                    evicted=1,
                )
        return await call_next(request)
