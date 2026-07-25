"""Tests for internal OAuth session preview used by Connect UI."""

from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.hosted import oauth_internal_session
from cartesia_mcp.oauth_store import MemoryBackend, oauth_store
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull


def _reset_store() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


def _client() -> TestClient:
    app = Starlette(
        routes=[
            Route(
                "/internal/oauth/session",
                endpoint=oauth_internal_session,
                methods=["POST"],
            )
        ]
    )
    return TestClient(app)


def test_oauth_internal_session_returns_client_metadata(monkeypatch):
    _reset_store()
    monkeypatch.setenv("MCP_INTERNAL_SECRET", "test-secret")

    client_info = OAuthClientInformationFull(
        client_id="preview-client",
        client_secret=None,
        redirect_uris=[AnyUrl("cursor://anysphere.cursor-mcp/oauth/callback")],
        client_name="Cursor",
        token_endpoint_auth_method="none",
    )
    oauth_store.register_client(client_info)
    session_id, connect_token = oauth_store.create_pending_session(
        client_info.client_id,
        AuthorizationParams(
            state="s",
            scopes=["mcp"],
            code_challenge="challenge",
            redirect_uri=AnyUrl("cursor://anysphere.cursor-mcp/oauth/callback"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )

    response = _client().post(
        "/internal/oauth/session",
        headers={"Authorization": "Bearer test-secret"},
        json={"session_id": session_id, "connect_token": connect_token},
    )
    assert response.status_code == 200
    assert response.json() == {
        "client_id": "preview-client",
        "client_name": "Cursor",
        "redirect_uri": "cursor://anysphere.cursor-mcp/oauth/callback",
    }


def test_oauth_internal_session_rejects_bad_token(monkeypatch):
    _reset_store()
    monkeypatch.setenv("MCP_INTERNAL_SECRET", "test-secret")

    response = _client().post(
        "/internal/oauth/session",
        headers={"Authorization": "Bearer wrong"},
        json={"session_id": "x", "connect_token": "y"},
    )
    assert response.status_code == 401


def test_oauth_internal_session_unknown_session(monkeypatch):
    _reset_store()
    monkeypatch.setenv("MCP_INTERNAL_SECRET", "test-secret")

    response = _client().post(
        "/internal/oauth/session",
        headers={"Authorization": "Bearer test-secret"},
        json={"session_id": "missing", "connect_token": "missing"},
    )
    assert response.status_code == 404
