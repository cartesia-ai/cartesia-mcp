"""Log org/user/client, JSON-RPC method, and tool-call outcome for hosted /mcp."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from cartesia_mcp.credentials import looks_like_cartesia_api_key
from cartesia_mcp.mcp_host_client import remember_host_client, resolve_host_client
from cartesia_mcp.mcp_http import (
    bearer_token,
    is_mcp_path,
    jsonrpc_client_info_from_body,
    jsonrpc_method_from_body,
    jsonrpc_tool_name_from_body,
    mcp_credential_key,
    redirect_fingerprint,
    request_protocol_version,
    request_user_agent,
)
from cartesia_mcp.mcp_session_guard import bound_session_count, report_tool_call
from cartesia_mcp.oauth_store import oauth_store

logger = logging.getLogger("cartesia_mcp.mcp")


@dataclass(frozen=True)
class McpRequestIdentity:
    owner_id: str | None = None
    user_id: str | None = None
    client_name: str | None = None
    oauth_redirect: str | None = None
    auth: str | None = None


def mcp_request_identity(request: Request) -> McpRequestIdentity:
    token = bearer_token(request)
    if token is None:
        return McpRequestIdentity()
    stored = oauth_store.resolve_mcp_access_token(token)
    if stored is not None:
        client = oauth_store.get_client(stored.client_id)
        oauth_redirect = None
        client_name = None
        if client is not None:
            client_name = client.client_name
            if client.redirect_uris:
                oauth_redirect = redirect_fingerprint(client.redirect_uris[0])
        return McpRequestIdentity(
            owner_id=stored.owner_id,
            user_id=stored.user_id,
            client_name=client_name,
            oauth_redirect=oauth_redirect,
            auth="oauth",
        )
    if looks_like_cartesia_api_key(token):
        return McpRequestIdentity(auth="api_key")
    return McpRequestIdentity()


_MAX_TOOL_RESULT_BYTES = 256 * 1024


def tool_call_outcome(status: int, body: bytes | None) -> str:
    """Classify a tools/call HTTP response. Does not read streaming bodies."""
    if status >= 400:
        return "http_error"
    if not body:
        return "unknown"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return "unknown"
    if isinstance(payload, list):
        payload = payload[0] if payload and isinstance(payload[0], dict) else None
    if not isinstance(payload, dict):
        return "unknown"
    error = payload.get("error")
    if isinstance(error, dict):
        return "rpc_error"
    result = payload.get("result")
    if isinstance(result, dict) and result.get("isError") is True:
        return "tool_error"
    return "ok"


def _rebuild_response(response: Response, data: bytes) -> Response:
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(
        content=data,
        status_code=response.status_code,
        headers=headers,
        background=getattr(response, "background", None),
    )


async def _json_body_and_response(response: Response) -> tuple[bytes | None, Response]:
    """Buffer a JSON tool result so the log can see isError, then return those bytes."""
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return None, response
    existing = getattr(response, "body", None)
    iterator = getattr(response, "body_iterator", None)
    if (
        isinstance(existing, (bytes, bytearray, memoryview))
        and existing
        and iterator is None
    ):
        return bytes(existing), response
    if iterator is None:
        return None, response
    chunks: list[bytes] = []
    total = 0
    truncated = False
    async for chunk in iterator:
        piece = bytes(chunk)
        chunks.append(piece)
        total += len(piece)
        if total > _MAX_TOOL_RESULT_BYTES:
            truncated = True
            break
    if truncated:
        async for chunk in iterator:
            chunks.append(bytes(chunk))
        return None, _rebuild_response(response, b"".join(chunks))
    data = b"".join(chunks)
    return data or None, _rebuild_response(response, data)


class McpRequestLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not is_mcp_path(request.url.path):
            return await call_next(request)

        rpc_method: str | None = None
        tool_name: str | None = None
        init_client = None
        if request.method == "POST":
            body = await request.body()
            rpc_method = jsonrpc_method_from_body(body)
            if rpc_method == "tools/call":
                tool_name = jsonrpc_tool_name_from_body(body) or "other"
            elif rpc_method == "initialize":
                init_client = jsonrpc_client_info_from_body(body)

        request_session = request.headers.get(MCP_SESSION_ID_HEADER)
        credential_key = mcp_credential_key(request)
        bound = resolve_host_client(
            session_id=request_session,
            credential_key=credential_key,
        )
        identity = mcp_request_identity(request)
        response = await call_next(request)

        if init_client is not None:
            created_session = response.headers.get(MCP_SESSION_ID_HEADER)
            remember_host_client(
                init_client,
                session_id=created_session or request_session,
                credential_key=credential_key,
            )
            host = init_client
        else:
            host = bound or resolve_host_client(
                session_id=response.headers.get(MCP_SESSION_ID_HEADER)
                or request_session,
                credential_key=credential_key,
            )

        mcp_client = host.name if host is not None else None
        mcp_client_version = host.version if host is not None else None

        outcome: str | None = None
        if tool_name is not None:
            body, response = await _json_body_and_response(response)
            outcome = tool_call_outcome(response.status_code, body)
            report_tool_call(tool_name, outcome, mcp_client=mcp_client)
        fields: dict[str, object] = {
            "event": "mcp_request",
            "method": request.method,
            "rpc": rpc_method,
            "owner_id": identity.owner_id,
            "user_id": identity.user_id,
            "client_name": identity.client_name,
            "oauth_redirect": identity.oauth_redirect,
            "mcp_client": mcp_client,
            "mcp_client_version": mcp_client_version,
            "user_agent": request_user_agent(request),
            "protocol_version": request_protocol_version(request),
            "auth": identity.auth,
            "status": response.status_code,
            "sessions": bound_session_count(),
        }
        if tool_name is not None:
            fields["tool"] = tool_name
            fields["outcome"] = outcome
        logger.info(json.dumps(fields, separators=(",", ":")))
        return response
