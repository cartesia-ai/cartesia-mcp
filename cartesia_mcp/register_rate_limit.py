"""IP rate limiting for MCP OAuth Dynamic Client Registration."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from cartesia_mcp.oauth_store import oauth_store

REGISTER_RATE_LIMIT = 30
REGISTER_RATE_WINDOW_SECONDS = 60 * 60


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class RegisterRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "POST" and request.url.path.rstrip("/") == "/register":
            ip = client_ip(request)
            count = oauth_store.increment_register_attempts(
                ip,
                window_seconds=REGISTER_RATE_WINDOW_SECONDS,
            )
            if count > REGISTER_RATE_LIMIT:
                return JSONResponse(
                    {
                        "error": "too_many_requests",
                        "error_description": (
                            "Dynamic client registration rate limit exceeded"
                        ),
                    },
                    status_code=429,
                    headers={"Retry-After": str(REGISTER_RATE_WINDOW_SECONDS)},
                )
        return await call_next(request)
