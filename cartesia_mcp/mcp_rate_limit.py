"""Rate limiting for hosted Streamable HTTP /mcp."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from cartesia_mcp.mcp_http import (
    is_mcp_path,
    mcp_rate_limit_bucket,
)
from cartesia_mcp.oauth_store import oauth_store
from cartesia_mcp.register_rate_limit import client_ip
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER

# General /mcp burst; reconnect storms still need initialize-specific limits below.
MCP_RATE_LIMIT = 30
MCP_RATE_WINDOW_SECONDS = 10

# Secondary IP bucket so one egress cannot mint sessions across many API keys.
MCP_IP_RATE_LIMIT = 120
MCP_IP_RATE_WINDOW_SECONDS = 10

# New session handshakes are expensive; keep well below general /mcp throughput.
MCP_INITIALIZE_RATE_LIMIT = 5
MCP_INITIALIZE_RATE_WINDOW_SECONDS = 60
MCP_INITIALIZE_IP_RATE_LIMIT = 15


def _too_many_requests(retry_after: int, description: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": "too_many_requests",
            "error_description": description,
        },
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


class McpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in ("GET", "POST", "DELETE") or not is_mcp_path(
            request.url.path
        ):
            return await call_next(request)

        ip = client_ip(request)
        bucket = mcp_rate_limit_bucket(request)

        if bucket.startswith("tok:"):
            ip_count = oauth_store.increment_mcp_attempts(
                f"allip:{ip}",
                window_seconds=MCP_IP_RATE_WINDOW_SECONDS,
            )
            if ip_count > MCP_IP_RATE_LIMIT:
                return _too_many_requests(
                    MCP_IP_RATE_WINDOW_SECONDS,
                    "MCP request rate limit exceeded for this IP",
                )

        count = oauth_store.increment_mcp_attempts(
            bucket,
            window_seconds=MCP_RATE_WINDOW_SECONDS,
        )
        if count > MCP_RATE_LIMIT:
            return _too_many_requests(
                MCP_RATE_WINDOW_SECONDS,
                "MCP request rate limit exceeded",
            )

        if request.method == "POST" and request.headers.get(MCP_SESSION_ID_HEADER) is None:
            init_count = oauth_store.increment_mcp_attempts(
                f"init:{bucket}",
                window_seconds=MCP_INITIALIZE_RATE_WINDOW_SECONDS,
            )
            if init_count > MCP_INITIALIZE_RATE_LIMIT:
                return _too_many_requests(
                    MCP_INITIALIZE_RATE_WINDOW_SECONDS,
                    "MCP session creation rate limit exceeded",
                )

            if bucket.startswith("tok:"):
                ip_init_count = oauth_store.increment_mcp_attempts(
                    f"initallip:{ip}",
                    window_seconds=MCP_INITIALIZE_RATE_WINDOW_SECONDS,
                )
                if ip_init_count > MCP_INITIALIZE_IP_RATE_LIMIT:
                    return _too_many_requests(
                        MCP_INITIALIZE_RATE_WINDOW_SECONDS,
                        "MCP session creation rate limit exceeded for this IP",
                    )

        return await call_next(request)
