"""Hosted Streamable HTTP MCP server configuration and routes."""

from __future__ import annotations

import hmac
from typing import Any

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from cartesia_mcp.branding import ICON_PNG_PATH
from cartesia_mcp.config import env_or_none
from cartesia_mcp.oauth_provider import CartesiaOAuthProvider
from cartesia_mcp.oauth_store import configure_oauth_store_from_env

_ICON_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


def hosted_enabled() -> bool:
    value = env_or_none("MCP_HOSTED")
    if value is None:
        return False
    return value.lower() in ("1", "true", "yes", "on")


def configure_hosted_oauth_store() -> None:
    """Require Redis for hosted OAuth state (fail closed if REDIS_URL is missing)."""
    configure_oauth_store_from_env(
        hosted=True,
        redis_url=env_or_none("REDIS_URL"),
    )


def server_public_url() -> str:
    return (env_or_none("MCP_SERVER_URL") or "http://127.0.0.1:8000").rstrip("/")


def mcp_resource_url() -> str:
    return f"{server_public_url()}/mcp"


def playground_public_url() -> str:
    return (env_or_none("PLAYGROUND_URL") or "https://play.cartesia.ai").rstrip("/")


def internal_secret() -> str | None:
    return env_or_none("MCP_INTERNAL_SECRET")


def hosted_bind_host() -> str:
    return "0.0.0.0"


def hosted_bind_port() -> int:
    return int(env_or_none("PORT") or "8000")


def hosted_server_kwargs() -> dict[str, Any]:
    """Constructor kwargs for MCPServer (auth only; transport moved to the app factory)."""
    mcp_url = server_public_url()
    provider = CartesiaOAuthProvider(
        playground_url=playground_public_url(),
        mcp_server_url=mcp_url,
    )
    return {
        "auth_server_provider": provider,
        "auth": AuthSettings(
            issuer_url=AnyHttpUrl(mcp_url),
            resource_server_url=AnyHttpUrl(mcp_resource_url()),
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["mcp"],
                default_scopes=["mcp"],
            ),
            required_scopes=["mcp"],
        ),
    }


def hosted_streamable_http_kwargs() -> dict[str, Any]:
    """Kwargs for MCPServer.streamable_http_app().

    ``host="0.0.0.0"`` keeps DNS-rebinding auto-protection off so public Host
    headers like mcp.cartesia.ai are accepted (v2 defaults host to 127.0.0.1).

    Stateful sessions emit ``Mcp-Session-Id`` and keep GET /mcp SSE open.
    Stateless mode never assigns a session id (logs ``Terminating session: None``)
    and some Streamable HTTP clients reconnect in a tight initialize/list/SSE
    loop. Hosted MCP is a single Render replica, so in-memory sessions are OK;
    deploys drop them and clients reconnect once.
    """
    return {
        "streamable_http_path": "/mcp",
        "stateless_http": False,
        "host": hosted_bind_host(),
    }


def _authorized_internal(request: Request) -> bool:
    secret = internal_secret()
    if not secret:
        return False
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    token = auth[7:]
    return hmac.compare_digest(token, secret)


async def health(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def icon_png(_: Request) -> Response:
    return FileResponse(
        ICON_PNG_PATH,
        media_type="image/png",
        headers=_ICON_CACHE_HEADERS,
    )


async def oauth_internal_complete(request: Request) -> Response:
    if not _authorized_internal(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    session_id = body.get("session_id")
    connect_token = body.get("connect_token")
    cartesia_credential = body.get("cartesia_credential")
    completing_owner_id = body.get("completing_owner_id")
    completing_user_id = body.get("completing_user_id")
    cartesia_admin_credential = body.get("cartesia_admin_credential")
    if (
        not session_id
        or not connect_token
        or not cartesia_credential
        or not completing_owner_id
        or not completing_user_id
    ):
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    from cartesia_mcp.oauth_store import oauth_store

    provider = CartesiaOAuthProvider(
        playground_url=playground_public_url(),
        mcp_server_url=server_public_url(),
    )

    completed = oauth_store.get_completed_session(
        session_id,
        connect_token,
        completing_owner_id,
        completing_user_id,
    )
    if completed is not None:
        try:
            redirect_url = provider.build_resume_redirect(session_id, completed)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"redirect_url": redirect_url})

    try:
        pending = oauth_store.attach_credential(
            session_id,
            connect_token,
            cartesia_credential,
            completing_owner_id=completing_owner_id,
            completing_user_id=completing_user_id,
            cartesia_admin_credential=cartesia_admin_credential,
        )
        redirect_url = provider.build_resume_redirect(session_id, pending)
    except KeyError:
        return JSONResponse({"error": "unknown_session"}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    oauth_store.remember_completed_session(
        session_id,
        connect_token,
        completing_owner_id,
        completing_user_id,
        pending,
    )
    try:
        oauth_store.pop_pending(session_id)
    except KeyError:
        pass
    return JSONResponse({"redirect_url": redirect_url})


async def oauth_internal_session(request: Request) -> Response:
    """Return pending OAuth client_name + redirect_uri for the Connect UI."""
    if not _authorized_internal(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    session_id = body.get("session_id")
    connect_token = body.get("connect_token")
    if not session_id or not connect_token:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    from cartesia_mcp.oauth_store import oauth_store

    try:
        pending = oauth_store.get_pending_session(session_id, connect_token)
    except KeyError:
        return JSONResponse({"error": "unknown_session"}, status_code=404)

    client = oauth_store.get_client(pending.client_id)
    return JSONResponse(
        {
            "client_id": pending.client_id,
            "client_name": client.client_name if client is not None else None,
            "redirect_uri": str(pending.params.redirect_uri),
        }
    )


def attach_hosted_routes(mcp: MCPServer) -> None:
    mcp._custom_starlette_routes.extend(
        [
            Route("/health", endpoint=health, methods=["GET"]),
            Route("/icon.png", endpoint=icon_png, methods=["GET"]),
            Route("/favicon.ico", endpoint=icon_png, methods=["GET"]),
            Route(
                "/internal/oauth/complete",
                endpoint=oauth_internal_complete,
                methods=["POST"],
            ),
            Route(
                "/internal/oauth/session",
                endpoint=oauth_internal_session,
                methods=["POST"],
            ),
        ]
    )


def run_hosted(mcp: MCPServer) -> None:
    if hosted_enabled():
        configure_hosted_oauth_store()
    attach_hosted_routes(mcp)

    import uvicorn

    from cartesia_mcp.mcp_rate_limit import McpRateLimitMiddleware
    from cartesia_mcp.mcp_request_log import McpRequestLogMiddleware
    from cartesia_mcp.mcp_session_guard import (
        McpSessionCapMiddleware,
        configure_hosted_session_manager,
    )
    from cartesia_mcp.register_rate_limit import RegisterRateLimitMiddleware

    app = mcp.streamable_http_app(**hosted_streamable_http_kwargs())
    configure_hosted_session_manager(mcp.session_manager)
    app.add_middleware(
        McpSessionCapMiddleware,
        session_manager=mcp.session_manager,
    )
    app.add_middleware(McpRateLimitMiddleware)
    app.add_middleware(McpRequestLogMiddleware)
    app.add_middleware(RegisterRateLimitMiddleware)
    uvicorn.run(
        app,
        host=hosted_bind_host(),
        port=hosted_bind_port(),
        log_level="info",
    )
