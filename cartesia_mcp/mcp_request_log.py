"""Log org/user/client and JSON-RPC method for hosted /mcp requests."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from cartesia_mcp.credentials import looks_like_cartesia_api_key
from cartesia_mcp.mcp_http import bearer_token, is_mcp_path, jsonrpc_method_from_body
from cartesia_mcp.oauth_store import oauth_store

logger = logging.getLogger("cartesia_mcp.mcp")


@dataclass(frozen=True)
class McpRequestIdentity:
    owner_id: str | None = None
    user_id: str | None = None
    client_name: str | None = None
    auth: str | None = None


def mcp_request_identity(request: Request) -> McpRequestIdentity:
    token = bearer_token(request)
    if token is None:
        return McpRequestIdentity()
    stored = oauth_store.resolve_mcp_access_token(token)
    if stored is not None:
        client = oauth_store.get_client(stored.client_id)
        return McpRequestIdentity(
            owner_id=stored.owner_id,
            user_id=stored.user_id,
            client_name=client.client_name if client is not None else None,
            auth="oauth",
        )
    if looks_like_cartesia_api_key(token):
        return McpRequestIdentity(auth="api_key")
    return McpRequestIdentity()


class McpRequestLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not is_mcp_path(request.url.path):
            return await call_next(request)

        rpc_method: str | None = None
        if request.method == "POST":
            rpc_method = jsonrpc_method_from_body(await request.body())
        identity = mcp_request_identity(request)
        response = await call_next(request)
        logger.info(
            "mcp request method=%s rpc=%s owner_id=%s user_id=%s "
            "client_name=%s auth=%s status=%s",
            request.method,
            rpc_method or "-",
            identity.owner_id or "-",
            identity.user_id or "-",
            identity.client_name or "-",
            identity.auth or "-",
            response.status_code,
        )
        return response
