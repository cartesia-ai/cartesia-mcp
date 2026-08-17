"""Tests for hosted /mcp request logging."""

import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.mcp_http import jsonrpc_method_from_body
from cartesia_mcp.mcp_request_log import McpRequestLogMiddleware
from cartesia_mcp.oauth_provider import CartesiaOAuthProvider
from cartesia_mcp.oauth_store import MemoryBackend, oauth_store
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


def _reset_store() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


async def _ok_mcp(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _client_app() -> TestClient:
    app = Starlette(
        routes=[
            Route("/mcp", endpoint=_ok_mcp, methods=["GET", "POST"]),
            Route("/health", endpoint=_ok_mcp, methods=["GET"]),
        ]
    )
    app.add_middleware(McpRequestLogMiddleware)
    return TestClient(app)


def _mint_oauth_token() -> str:
    client = OAuthClientInformationFull(
        client_id="log-client",
        client_secret=None,
        redirect_uris=[AnyUrl("cursor://callback")],
        client_name="Cursor",
        token_endpoint_auth_method="none",
    )
    oauth_store.register_client(client)
    session_id, connect_token = oauth_store.create_pending_session(
        client.client_id,
        AuthorizationParams(
            state="s",
            scopes=["mcp"],
            code_challenge="challenge",
            redirect_uri=AnyUrl("cursor://callback"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    oauth_store.attach_credential(
        session_id,
        connect_token,
        "sk_car_oauth_test_key",
        completing_owner_id="org_logged",
        completing_user_id="user_logged",
    )
    pending = oauth_store.pop_pending(session_id)
    provider = CartesiaOAuthProvider(
        playground_url="https://play.cartesia.ai",
        mcp_server_url="https://mcp.cartesia.ai",
    )
    redirect = provider.build_resume_redirect(session_id, pending)
    auth_code = oauth_store.load_authorization_code(
        client,
        redirect.split("code=")[1].split("&")[0],
    )
    assert auth_code is not None
    token = oauth_store.exchange_authorization_code(client, auth_code)
    return token.access_token


def test_jsonrpc_method_from_body_reads_initialize():
    assert (
        jsonrpc_method_from_body(b'{"jsonrpc":"2.0","method":"initialize","id":1}')
        == "initialize"
    )
    assert jsonrpc_method_from_body(b'[{"method":"tools/list"}]') == "tools/list"
    assert jsonrpc_method_from_body(b"not-json") is None
    assert jsonrpc_method_from_body(b'{"params":{}}') is None


def test_mcp_request_log_includes_owner_and_rpc(caplog):
    _reset_store()
    access = _mint_oauth_token()
    client = _client_app()
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        response = client.post(
            "/mcp",
            headers={"authorization": f"Bearer {access}"},
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
    assert response.status_code == 200
    records = [r.getMessage() for r in caplog.records if "mcp request" in r.getMessage()]
    assert records
    message = records[-1]
    assert "rpc=tools/list" in message
    assert "owner_id=org_logged" in message
    assert "user_id=user_logged" in message
    assert "client_name=Cursor" in message
    assert "auth=oauth" in message
    assert access not in message
    assert "sk_car_oauth_test_key" not in message


def test_mcp_request_log_skips_health(caplog):
    _reset_store()
    client = _client_app()
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        assert client.get("/health").status_code == 200
    assert not [r for r in caplog.records if "mcp request" in r.getMessage()]
