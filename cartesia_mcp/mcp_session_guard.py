"""Cap concurrent Streamable HTTP MCP sessions on the hosted server."""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from cartesia_mcp.mcp_http import is_mcp_path, mcp_rate_limit_bucket

logger = logging.getLogger("cartesia_mcp.mcp")

# In-memory sessions on one replica. One live session per client bucket.
# At cap, also reclaim idle LRU, else 503. Never evict a hot other client.
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


def _ensure_dict(session_manager: StreamableHTTPSessionManager, attr: str) -> dict:
    value = getattr(session_manager, attr, None)
    if not isinstance(value, dict):
        value = {}
        setattr(session_manager, attr, value)
    return value


def _last_seen_at(
    session_manager: StreamableHTTPSessionManager,
    session_id: str,
) -> float:
    last_seen = getattr(session_manager, "_session_last_seen", None)
    if not isinstance(last_seen, dict):
        return 0.0
    seen = last_seen.get(session_id)
    if not isinstance(seen, (int, float)):
        return 0.0
    return float(seen)


async def _terminate_session(
    session_manager: StreamableHTTPSessionManager,
    session_id: str,
) -> str | None:
    transport = session_manager._server_instances.pop(session_id, None)
    if transport is None:
        return None
    # `_session_owners` is the SDK principal map; `_session_buckets` is ours.
    for attr in ("_session_owners", "_session_buckets", "_session_last_seen"):
        meta = getattr(session_manager, attr, None)
        if isinstance(meta, dict):
            meta.pop(session_id, None)
    terminate = getattr(transport, "terminate", None)
    if callable(terminate):
        await terminate()
    return session_id


async def _replace_owned_session(
    session_manager: StreamableHTTPSessionManager,
    bucket: str,
) -> str | None:
    instances = session_manager._server_instances
    buckets = getattr(session_manager, "_session_buckets", None)
    owned = [
        session_id
        for session_id, owner in (buckets.items() if isinstance(buckets, dict) else ())
        if owner == bucket and session_id in instances
    ]
    if not owned:
        return None
    victim = min(owned, key=lambda session_id: _last_seen_at(session_manager, session_id))
    return await _terminate_session(session_manager, victim)


async def _evict_idle_session(
    session_manager: StreamableHTTPSessionManager,
) -> str | None:
    idle_deadline = time.monotonic() - MCP_SESSION_IDLE_TIMEOUT_SECONDS
    idle = [
        session_id
        for session_id in session_manager._server_instances
        if _last_seen_at(session_manager, session_id) <= idle_deadline
    ]
    if not idle:
        return None
    victim = min(idle, key=lambda session_id: _last_seen_at(session_manager, session_id))
    return await _terminate_session(session_manager, victim)


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
        if not is_mcp_path(request.url.path):
            return await call_next(request)

        session_id = request.headers.get(MCP_SESSION_ID_HEADER)
        if session_id is not None:
            if session_id in self._session_manager._server_instances:
                _ensure_dict(self._session_manager, "_session_last_seen")[session_id] = (
                    time.monotonic()
                )
            return await call_next(request)

        if request.method not in _NEW_SESSION_METHODS:
            return await call_next(request)

        bucket = mcp_rate_limit_bucket(request)
        active = active_session_count(self._session_manager)
        report_session_metrics(active)
        evicted = await _replace_owned_session(self._session_manager, bucket)
        reason = "replace" if evicted else None
        if evicted is None and active >= MCP_MAX_CONCURRENT_SESSIONS:
            evicted = await _evict_idle_session(self._session_manager)
            if evicted is None:
                return JSONResponse(
                    {
                        "error": "service_unavailable",
                        "error_description": "Too many active MCP sessions",
                    },
                    status_code=503,
                    headers={"Retry-After": "30"},
                )
            reason = "idle"
        if evicted is not None:
            logger.warning(
                json.dumps(
                    {
                        "event": "mcp_session_evicted",
                        "active": active,
                        "cap": MCP_MAX_CONCURRENT_SESSIONS,
                        "evicted": evicted,
                        "reason": reason,
                    },
                    separators=(",", ":"),
                )
            )
            report_session_metrics(
                active_session_count(self._session_manager),
                evicted=1,
            )

        response = await call_next(request)
        created = response.headers.get(MCP_SESSION_ID_HEADER)
        if created:
            _ensure_dict(self._session_manager, "_session_buckets")[created] = bucket
            _ensure_dict(self._session_manager, "_session_last_seen")[created] = time.monotonic()
        return response
