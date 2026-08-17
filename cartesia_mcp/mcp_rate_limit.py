"""Rate limiting for hosted Streamable HTTP /mcp."""

from __future__ import annotations

import hashlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from cartesia_mcp.oauth_store import oauth_store
from cartesia_mcp.register_rate_limit import client_ip

# Burst of ~60 in 10s covers initialize + tools/list + SSE; tens of rps reconnects trip it.
MCP_RATE_LIMIT = 60
MCP_RATE_WINDOW_SECONDS = 10


def is_mcp_path(path: str) -> bool:
    return path.rstrip("/") == "/mcp"


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token or None


def mcp_rate_limit_bucket(request: Request) -> str:
    """Prefer a hashed bearer so shared egress IPs do not share one bucket."""
    token = bearer_token(request)
    if token is not None:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return f"tok:{digest}"
    return f"ip:{client_ip(request)}"


class McpRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in ("GET", "POST", "DELETE") and is_mcp_path(request.url.path):
            bucket = mcp_rate_limit_bucket(request)
            count = oauth_store.increment_mcp_attempts(
                bucket,
                window_seconds=MCP_RATE_WINDOW_SECONDS,
            )
            if count > MCP_RATE_LIMIT:
                return JSONResponse(
                    {
                        "error": "too_many_requests",
                        "error_description": "MCP request rate limit exceeded",
                    },
                    status_code=429,
                    headers={"Retry-After": str(MCP_RATE_WINDOW_SECONDS)},
                )
        return await call_next(request)
