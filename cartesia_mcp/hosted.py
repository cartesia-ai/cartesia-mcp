"""Hosted Streamable HTTP MCP server configuration and routes."""

from __future__ import annotations

import hmac
import os
from typing import Any

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from cartesia_mcp.config import env_or_none
from cartesia_mcp.oauth_provider import CartesiaOAuthProvider


def hosted_enabled() -> bool:
    return bool(env_or_none("MCP_HOSTED"))


def server_public_url() -> str:
    return (env_or_none("MCP_SERVER_URL") or "http://127.0.0.1:8000").rstrip("/")


def playground_public_url() -> str:
    return (env_or_none("PLAYGROUND_URL") or "https://play.cartesia.ai").rstrip("/")


def internal_secret() -> str | None:
    return env_or_none("MCP_INTERNAL_SECRET")


def fastmcp_hosted_kwargs() -> dict[str, Any]:
    mcp_url = server_public_url()
    provider = CartesiaOAuthProvider(
        playground_url=playground_public_url(),
        mcp_server_url=mcp_url,
    )
    return {
        "host": "0.0.0.0",
        "port": int(env_or_none("PORT") or "8000"),
        "streamable_http_path": "/mcp",
        "stateless_http": True,
        "auth_server_provider": provider,
        "auth": AuthSettings(
            issuer_url=AnyHttpUrl(mcp_url),
            resource_server_url=AnyHttpUrl(mcp_url),
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["mcp"],
                default_scopes=["mcp"],
            ),
            required_scopes=["mcp"],
        ),
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


async def oauth_internal_complete(request: Request) -> Response:
    if not _authorized_internal(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    session_id = body.get("session_id")
    cartesia_credential = body.get("cartesia_credential")
    cartesia_admin_credential = body.get("cartesia_admin_credential")
    if not session_id or not cartesia_credential:
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    from cartesia_mcp.oauth_store import oauth_store

    try:
        pending = oauth_store.attach_credential(
            session_id,
            cartesia_credential,
            cartesia_admin_credential=cartesia_admin_credential,
        )
    except KeyError:
        return JSONResponse({"error": "unknown_session"}, status_code=404)

    provider = CartesiaOAuthProvider(
        playground_url=playground_public_url(),
        mcp_server_url=server_public_url(),
    )
    redirect_url = provider.build_resume_redirect(session_id, pending)
    oauth_store.pop_pending(session_id)
    return JSONResponse({"redirect_url": redirect_url})


async def oauth_browser_resume(request: Request) -> Response:
    session_id = request.query_params.get("session")
    if not session_id:
        return JSONResponse({"error": "missing session"}, status_code=400)

    from cartesia_mcp.oauth_store import oauth_store

    try:
        pending = oauth_store.pop_pending(session_id)
    except KeyError:
        return JSONResponse({"error": "unknown_session"}, status_code=404)

    if not pending.cartesia_credential:
        return JSONResponse({"error": "session_not_ready"}, status_code=400)

    provider = CartesiaOAuthProvider(
        playground_url=playground_public_url(),
        mcp_server_url=server_public_url(),
    )
    redirect_url = provider.build_resume_redirect(session_id, pending)
    return RedirectResponse(redirect_url, status_code=302)


def attach_hosted_routes(mcp: FastMCP) -> None:
    mcp._custom_starlette_routes.extend(
        [
            Route("/health", endpoint=health, methods=["GET"]),
            Route(
                "/internal/oauth/complete",
                endpoint=oauth_internal_complete,
                methods=["POST"],
            ),
            Route(
                "/oauth/resume",
                endpoint=oauth_browser_resume,
                methods=["GET"],
            ),
        ]
    )


def run_hosted(mcp: FastMCP) -> None:
    attach_hosted_routes(mcp)
    mcp.run(transport="streamable-http")
