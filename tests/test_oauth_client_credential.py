"""Reconnects reuse the bearer stored for one organization and MCP client."""

from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from cartesia_mcp.hosted import oauth_internal_complete, oauth_internal_session
from cartesia_mcp.oauth_store import MemoryBackend, oauth_store

OWNER_ID = "org_reconnect"
USER_ID = "user_reconnect"
BEARER = "sk_car_oauth_test_key"
ADMIN_BEARER = "sk_car_admin_oauth_test"
REDIRECT = "cursor://anysphere.cursor-mcp/oauth/callback"


def _reset_store() -> None:
    oauth_store.use_backend(MemoryBackend())
    oauth_store.clear()


def _client() -> TestClient:
    app = Starlette(
        routes=[
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
    return TestClient(app)


def _register(client_id: str, client_name: str) -> None:
    oauth_store.register_client(
        OAuthClientInformationFull(
            client_id=client_id,
            client_secret=None,
            redirect_uris=[AnyUrl(REDIRECT)],
            client_name=client_name,
            token_endpoint_auth_method="none",
        )
    )


def _pending(client_id: str) -> tuple[str, str]:
    return oauth_store.create_pending_session(
        client_id,
        AuthorizationParams(
            state="s",
            scopes=["mcp"],
            code_challenge="challenge",
            redirect_uri=AnyUrl(REDIRECT),
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-secret"}


def test_complete_stores_credential_and_session_reports_it_without_the_bearer(
    monkeypatch,
):
    _reset_store()
    monkeypatch.setenv("MCP_INTERNAL_SECRET", "test-secret")
    _register("cursor-client", "Cursor")
    session_id, connect_token = _pending("cursor-client")
    http = _client()

    completed = http.post(
        "/internal/oauth/complete",
        headers=_auth_headers(),
        json={
            "session_id": session_id,
            "connect_token": connect_token,
            "cartesia_credential": BEARER,
            "completing_owner_id": OWNER_ID,
            "completing_user_id": USER_ID,
        },
    )
    assert completed.status_code == 200
    assert BEARER not in completed.text
    assert oauth_store.has_client_credential(OWNER_ID, "cursor-client")

    preview_id, preview_token = _pending("cursor-client")
    preview = http.post(
        "/internal/oauth/session",
        headers=_auth_headers(),
        json={
            "session_id": preview_id,
            "connect_token": preview_token,
            "owner_id": OWNER_ID,
        },
    )
    assert preview.status_code == 200
    assert preview.json()["has_stored_credential"] is True
    assert BEARER not in preview.text

    other_owner = http.post(
        "/internal/oauth/session",
        headers=_auth_headers(),
        json={
            "session_id": preview_id,
            "connect_token": preview_token,
            "owner_id": "org_other",
        },
    )
    assert other_owner.json()["has_stored_credential"] is False


def test_reuse_attaches_the_stored_bearer_for_the_same_client(monkeypatch):
    _reset_store()
    monkeypatch.setenv("MCP_INTERNAL_SECRET", "test-secret")
    _register("cursor-client", "Cursor")
    _register("claude-client", "Claude")
    http = _client()

    first_id, first_token = _pending("cursor-client")
    first = http.post(
        "/internal/oauth/complete",
        headers=_auth_headers(),
        json={
            "session_id": first_id,
            "connect_token": first_token,
            "cartesia_credential": BEARER,
            "completing_owner_id": OWNER_ID,
            "completing_user_id": USER_ID,
        },
    )
    assert first.status_code == 200

    second_id, second_token = _pending("cursor-client")
    reused = http.post(
        "/internal/oauth/complete",
        headers=_auth_headers(),
        json={
            "session_id": second_id,
            "connect_token": second_token,
            "reuse_credential": True,
            "cartesia_admin_credential": ADMIN_BEARER,
            "completing_owner_id": OWNER_ID,
            "completing_user_id": USER_ID,
        },
    )
    assert reused.status_code == 200
    assert BEARER not in reused.text
    assert ADMIN_BEARER not in reused.text
    code = parse_qs(urlparse(reused.json()["redirect_url"]).query)["code"][0]
    client = oauth_store.get_client("cursor-client")
    assert client is not None
    auth_code = oauth_store.load_authorization_code(client, code)
    assert auth_code is not None
    token = oauth_store.exchange_authorization_code(client, auth_code)
    access = oauth_store.resolve_mcp_access_token(token.access_token)
    assert access is not None
    assert access.cartesia_credential == BEARER
    assert access.cartesia_admin_credential == ADMIN_BEARER

    other_id, other_token = _pending("claude-client")
    missing = http.post(
        "/internal/oauth/complete",
        headers=_auth_headers(),
        json={
            "session_id": other_id,
            "connect_token": other_token,
            "reuse_credential": True,
            "completing_owner_id": OWNER_ID,
            "completing_user_id": USER_ID,
        },
    )
    assert missing.status_code == 404
    assert missing.json()["error"] == "credential_not_found"


def test_complete_rejects_reuse_combined_with_a_new_bearer(monkeypatch):
    _reset_store()
    monkeypatch.setenv("MCP_INTERNAL_SECRET", "test-secret")
    _register("cursor-client", "Cursor")
    session_id, connect_token = _pending("cursor-client")

    response = _client().post(
        "/internal/oauth/complete",
        headers=_auth_headers(),
        json={
            "session_id": session_id,
            "connect_token": connect_token,
            "cartesia_credential": BEARER,
            "reuse_credential": True,
            "completing_owner_id": OWNER_ID,
            "completing_user_id": USER_ID,
        },
    )
    assert response.status_code == 400
    assert not oauth_store.has_client_credential(OWNER_ID, "cursor-client")
