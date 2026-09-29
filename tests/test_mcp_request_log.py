"""Tests for hosted /mcp request logging."""

import json
import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.mcp_http import jsonrpc_method_from_body, jsonrpc_tool_name_from_body
from cartesia_mcp.mcp_request_log import McpRequestLogMiddleware, tool_call_outcome
from cartesia_mcp.oauth_provider import CartesiaOAuthProvider
from cartesia_mcp.oauth_store import MemoryBackend, oauth_store
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl


def _mcp_request_payloads(caplog) -> list[dict]:
    payloads: list[dict] = []
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith("{"):
            continue
        payload = json.loads(message)
        if payload.get("event") == "mcp_request":
            payloads.append(payload)
    return payloads


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


def test_jsonrpc_tool_name_from_body_reads_tools_call():
    body = b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"text_to_speech"}}'
    assert jsonrpc_tool_name_from_body(body) == "text_to_speech"
    assert jsonrpc_tool_name_from_body(b'{"method":"tools/list"}') is None
    weird = b'{"method":"tools/call","params":{"name":"text to speech"}}'
    assert jsonrpc_tool_name_from_body(weird) is None


def test_tool_call_outcome_classifies_json_results():
    ok = b'{"jsonrpc":"2.0","result":{"content":[]}}'
    assert tool_call_outcome(200, ok) == "ok"
    tool_error = b'{"jsonrpc":"2.0","result":{"isError":true,"content":[]}}'
    assert tool_call_outcome(200, tool_error) == "tool_error"
    rpc_error = b'{"jsonrpc":"2.0","error":{"code":-32602,"message":"bad"}}'
    assert tool_call_outcome(200, rpc_error) == "rpc_error"
    assert tool_call_outcome(429, ok) == "http_error"
    assert tool_call_outcome(200, None) == "unknown"


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
    payloads = _mcp_request_payloads(caplog)
    assert payloads
    payload = payloads[-1]
    assert payload["rpc"] == "tools/list"
    assert payload["owner_id"] == "org_logged"
    assert payload["user_id"] == "user_logged"
    assert payload["client_name"] == "Cursor"
    assert payload["auth"] == "oauth"
    assert payload["status"] == 200
    assert isinstance(payload["sessions"], int)
    message = json.dumps(payload)
    assert access not in message
    assert "sk_car_oauth_test_key" not in message


def test_mcp_request_log_records_tool_call(caplog):
    _reset_store()
    client = _client_app()
    body = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,
        "params": {"name": "speech_to_text", "arguments": {"file_id": "file_123"}},
    }
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        response = client.post("/mcp", json=body)
    assert response.status_code == 200
    payload = _mcp_request_payloads(caplog)[-1]
    assert payload["rpc"] == "tools/call"
    assert payload["tool"] == "speech_to_text"
    assert payload["outcome"] == "ok"
    assert "file_123" not in json.dumps(payload)


def test_mcp_request_log_marks_tool_errors(caplog):
    _reset_store()

    async def _tool_error(_: Request) -> JSONResponse:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": []}}
        )

    app = Starlette(routes=[Route("/mcp", endpoint=_tool_error, methods=["POST"])])
    app.add_middleware(McpRequestLogMiddleware)
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "get_voice"}},
        )
    payload = _mcp_request_payloads(caplog)[-1]
    assert payload["tool"] == "get_voice"
    assert payload["outcome"] == "tool_error"


def test_mcp_request_log_skips_health(caplog):
    _reset_store()
    client = _client_app()
    with caplog.at_level(logging.INFO, logger="cartesia_mcp.mcp"):
        assert client.get("/health").status_code == 200
    assert not _mcp_request_payloads(caplog)
