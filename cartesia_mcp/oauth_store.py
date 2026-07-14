"""OAuth state for hosted MCP (in-memory for tests; Redis required when hosted)."""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams, RefreshToken
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

AUTH_CODE_TTL_SECONDS = 600
PENDING_SESSION_TTL_SECONDS = 600
COMPLETED_SESSION_TTL_SECONDS = 600
ACCESS_TOKEN_TTL_SECONDS = 24 * 60 * 60
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60

_KEY_CLIENT = "mcp:oauth:client:"
_KEY_PENDING = "mcp:oauth:pending:"
_KEY_COMPLETED = "mcp:oauth:completed:"
_KEY_AUTH_CODE = "mcp:oauth:code:"
_KEY_CODE_CREDENTIALS = "mcp:oauth:code-cred:"
_KEY_ACCESS = "mcp:oauth:access:"
_KEY_REFRESH = "mcp:oauth:refresh:"


@dataclass
class PendingConnectSession:
    client_id: str
    params: AuthorizationParams
    connect_token: str
    cartesia_credential: str | None = None
    cartesia_admin_credential: str | None = None
    completing_owner_id: str | None = None
    completing_user_id: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class StoredMcpAccessToken:
    token: str
    cartesia_credential: str
    client_id: str
    scopes: list[str]
    expires_at: int
    cartesia_admin_credential: str | None = None
    refresh_token: str | None = None


@dataclass
class StoredMcpRefreshToken:
    token: str
    cartesia_credential: str
    client_id: str
    scopes: list[str]
    expires_at: int
    cartesia_admin_credential: str | None = None
    access_token: str | None = None


class StoreBackend(Protocol):
    def get_json(self, key: str) -> dict[str, Any] | None: ...

    def pop_json(self, key: str) -> dict[str, Any] | None: ...

    def set_json(
        self,
        key: str,
        value: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> None: ...

    def delete(self, key: str) -> None: ...

    def clear(self) -> None: ...


class MemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, tuple[dict[str, Any], float | None]] = {}

    def get_json(self, key: str) -> dict[str, Any] | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at < time.time():
            self._data.pop(key, None)
            return None
        return value

    def pop_json(self, key: str) -> dict[str, Any] | None:
        entry = self._data.pop(key, None)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at < time.time():
            return None
        return value

    def set_json(
        self,
        key: str,
        value: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None
        self._data[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


class RedisBackend:
    def __init__(self, redis_url: str) -> None:
        import redis

        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._redis.ping()

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def pop_json(self, key: str) -> dict[str, Any] | None:
        # GETDEL is atomic — only one redeeming request can win.
        raw = self._redis.getdel(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set_json(
        self,
        key: str,
        value: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        payload = json.dumps(value)
        if ttl_seconds is None:
            self._redis.set(key, payload)
        else:
            self._redis.setex(key, ttl_seconds, payload)

    def delete(self, key: str) -> None:
        self._redis.delete(key)

    def clear(self) -> None:
        raise RuntimeError("RedisBackend.clear() is not supported in production")


def _params_to_dict(params: AuthorizationParams) -> dict[str, Any]:
    return {
        "state": params.state,
        "scopes": list(params.scopes or []),
        "code_challenge": params.code_challenge,
        "redirect_uri": str(params.redirect_uri),
        "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
        "resource": params.resource,
    }


def _params_from_dict(data: dict[str, Any]) -> AuthorizationParams:
    return AuthorizationParams(
        state=data.get("state"),
        scopes=data.get("scopes"),
        code_challenge=data["code_challenge"],
        redirect_uri=AnyUrl(data["redirect_uri"]),
        redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
        resource=data.get("resource"),
    )


def _pending_to_dict(pending: PendingConnectSession) -> dict[str, Any]:
    return {
        "client_id": pending.client_id,
        "params": _params_to_dict(pending.params),
        "connect_token": pending.connect_token,
        "cartesia_credential": pending.cartesia_credential,
        "cartesia_admin_credential": pending.cartesia_admin_credential,
        "completing_owner_id": pending.completing_owner_id,
        "completing_user_id": pending.completing_user_id,
        "created_at": pending.created_at,
    }


def _pending_from_dict(data: dict[str, Any]) -> PendingConnectSession:
    return PendingConnectSession(
        client_id=data["client_id"],
        params=_params_from_dict(data["params"]),
        connect_token=data["connect_token"],
        cartesia_credential=data.get("cartesia_credential"),
        cartesia_admin_credential=data.get("cartesia_admin_credential"),
        completing_owner_id=data.get("completing_owner_id"),
        completing_user_id=data.get("completing_user_id"),
        created_at=float(data.get("created_at") or time.time()),
    )


def _access_to_dict(stored: StoredMcpAccessToken) -> dict[str, Any]:
    return {
        "token": stored.token,
        "cartesia_credential": stored.cartesia_credential,
        "client_id": stored.client_id,
        "scopes": list(stored.scopes),
        "expires_at": stored.expires_at,
        "cartesia_admin_credential": stored.cartesia_admin_credential,
        "refresh_token": stored.refresh_token,
    }


def _access_from_dict(data: dict[str, Any]) -> StoredMcpAccessToken:
    return StoredMcpAccessToken(
        token=data["token"],
        cartesia_credential=data["cartesia_credential"],
        client_id=data["client_id"],
        scopes=list(data.get("scopes") or []),
        expires_at=int(data["expires_at"]),
        cartesia_admin_credential=data.get("cartesia_admin_credential"),
        refresh_token=data.get("refresh_token"),
    )


def _refresh_to_dict(stored: StoredMcpRefreshToken) -> dict[str, Any]:
    return {
        "token": stored.token,
        "cartesia_credential": stored.cartesia_credential,
        "client_id": stored.client_id,
        "scopes": list(stored.scopes),
        "expires_at": stored.expires_at,
        "cartesia_admin_credential": stored.cartesia_admin_credential,
        "access_token": stored.access_token,
    }


def _refresh_from_dict(data: dict[str, Any]) -> StoredMcpRefreshToken:
    return StoredMcpRefreshToken(
        token=data["token"],
        cartesia_credential=data["cartesia_credential"],
        client_id=data["client_id"],
        scopes=list(data.get("scopes") or []),
        expires_at=int(data["expires_at"]),
        cartesia_admin_credential=data.get("cartesia_admin_credential"),
        access_token=data.get("access_token"),
    )


def _auth_code_to_dict(auth_code: AuthorizationCode) -> dict[str, Any]:
    return {
        "code": auth_code.code,
        "scopes": list(auth_code.scopes),
        "expires_at": auth_code.expires_at,
        "client_id": auth_code.client_id,
        "code_challenge": auth_code.code_challenge,
        "redirect_uri": str(auth_code.redirect_uri),
        "redirect_uri_provided_explicitly": auth_code.redirect_uri_provided_explicitly,
        "resource": auth_code.resource,
        "subject": auth_code.subject,
    }


def _auth_code_from_dict(data: dict[str, Any]) -> AuthorizationCode:
    return AuthorizationCode(
        code=data["code"],
        scopes=list(data.get("scopes") or []),
        expires_at=float(data["expires_at"]),
        client_id=data["client_id"],
        code_challenge=data["code_challenge"],
        redirect_uri=AnyUrl(data["redirect_uri"]),
        redirect_uri_provided_explicitly=data["redirect_uri_provided_explicitly"],
        resource=data.get("resource"),
        subject=data.get("subject"),
    )


class OAuthStore:
    def __init__(self, backend: StoreBackend | None = None) -> None:
        self._backend: StoreBackend = backend or MemoryBackend()

    def use_backend(self, backend: StoreBackend) -> None:
        self._backend = backend

    def clear(self) -> None:
        self._backend.clear()

    def register_client(self, client: OAuthClientInformationFull) -> None:
        self._backend.set_json(
            f"{_KEY_CLIENT}{client.client_id}",
            client.model_dump(mode="json"),
        )

    def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self._backend.get_json(f"{_KEY_CLIENT}{client_id}")
        if data is None:
            return None
        return OAuthClientInformationFull.model_validate(data)

    def create_pending_session(
        self,
        client_id: str,
        params: AuthorizationParams,
    ) -> tuple[str, str]:
        session_id = secrets.token_urlsafe(32)
        connect_token = secrets.token_urlsafe(32)
        pending = PendingConnectSession(
            client_id=client_id,
            params=params,
            connect_token=connect_token,
        )
        self._backend.set_json(
            f"{_KEY_PENDING}{session_id}",
            _pending_to_dict(pending),
            ttl_seconds=PENDING_SESSION_TTL_SECONDS,
        )
        return session_id, connect_token

    def get_pending_session(
        self,
        session_id: str,
        connect_token: str,
    ) -> PendingConnectSession:
        data = self._backend.get_json(f"{_KEY_PENDING}{session_id}")
        if data is None:
            raise KeyError(f"Unknown MCP OAuth session: {session_id}")
        pending = _pending_from_dict(data)
        if not secrets.compare_digest(pending.connect_token, connect_token):
            raise KeyError(f"Unknown MCP OAuth session: {session_id}")
        return pending

    def _save_pending(self, session_id: str, pending: PendingConnectSession) -> None:
        self._backend.set_json(
            f"{_KEY_PENDING}{session_id}",
            _pending_to_dict(pending),
            ttl_seconds=PENDING_SESSION_TTL_SECONDS,
        )

    def attach_credential(
        self,
        session_id: str,
        connect_token: str,
        cartesia_credential: str,
        *,
        completing_owner_id: str,
        completing_user_id: str,
        cartesia_admin_credential: str | None = None,
    ) -> PendingConnectSession:
        pending = self.get_pending_session(session_id, connect_token)
        if pending.cartesia_credential is not None:
            if (
                pending.completing_owner_id == completing_owner_id
                and pending.completing_user_id == completing_user_id
                and pending.cartesia_credential == cartesia_credential
            ):
                if cartesia_admin_credential:
                    pending.cartesia_admin_credential = cartesia_admin_credential
                    self._save_pending(session_id, pending)
                return pending
            raise ValueError("MCP OAuth session already completed")
        if (
            pending.completing_owner_id is not None
            and pending.completing_owner_id != completing_owner_id
        ):
            raise ValueError("MCP OAuth session bound to a different organization")
        pending.completing_owner_id = completing_owner_id
        pending.completing_user_id = completing_user_id
        pending.cartesia_credential = cartesia_credential
        pending.cartesia_admin_credential = cartesia_admin_credential
        self._save_pending(session_id, pending)
        return pending

    def remember_completed_session(
        self,
        session_id: str,
        connect_token: str,
        completing_owner_id: str,
        completing_user_id: str,
        pending: PendingConnectSession,
    ) -> None:
        key = self._completed_redirect_key(
            session_id,
            connect_token,
            completing_owner_id,
            completing_user_id,
        )
        self._backend.set_json(
            f"{_KEY_COMPLETED}{key}",
            _pending_to_dict(pending),
            ttl_seconds=COMPLETED_SESSION_TTL_SECONDS,
        )

    def get_completed_session(
        self,
        session_id: str,
        connect_token: str,
        completing_owner_id: str,
        completing_user_id: str,
    ) -> PendingConnectSession | None:
        key = self._completed_redirect_key(
            session_id,
            connect_token,
            completing_owner_id,
            completing_user_id,
        )
        data = self._backend.get_json(f"{_KEY_COMPLETED}{key}")
        if data is None:
            return None
        return _pending_from_dict(data)

    def _completed_redirect_key(
        self,
        session_id: str,
        connect_token: str,
        completing_owner_id: str,
        completing_user_id: str,
    ) -> str:
        return f"{session_id}:{connect_token}:{completing_owner_id}:{completing_user_id}"

    def pop_pending(self, session_id: str) -> PendingConnectSession:
        data = self._backend.get_json(f"{_KEY_PENDING}{session_id}")
        if data is None:
            raise KeyError(f"Unknown MCP OAuth session: {session_id}")
        self._backend.delete(f"{_KEY_PENDING}{session_id}")
        return _pending_from_dict(data)

    def issue_authorization_code(
        self,
        *,
        client_id: str,
        params: AuthorizationParams,
        cartesia_credential: str,
        cartesia_admin_credential: str | None = None,
    ) -> AuthorizationCode:
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            scopes=list(params.scopes or []),
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        self._backend.set_json(
            f"{_KEY_AUTH_CODE}{code}",
            _auth_code_to_dict(auth_code),
            ttl_seconds=AUTH_CODE_TTL_SECONDS,
        )
        self._backend.set_json(
            f"{_KEY_CODE_CREDENTIALS}{code}",
            {
                "cartesia_credential": cartesia_credential,
                "cartesia_admin_credential": cartesia_admin_credential,
                "client_id": client_id,
                "scopes": list(params.scopes or []),
            },
            ttl_seconds=AUTH_CODE_TTL_SECONDS,
        )
        return auth_code

    def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        data = self._backend.get_json(f"{_KEY_AUTH_CODE}{authorization_code}")
        if data is None:
            return None
        stored = _auth_code_from_dict(data)
        if stored.client_id != client.client_id:
            return None
        if stored.expires_at < time.time():
            return None
        return stored

    def _issue_token_pair(
        self,
        *,
        client_id: str,
        scopes: list[str],
        cartesia_credential: str,
        cartesia_admin_credential: str | None,
    ) -> OAuthToken:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = int(time.time())
        access_expires_at = now + ACCESS_TOKEN_TTL_SECONDS
        refresh_expires_at = now + REFRESH_TOKEN_TTL_SECONDS

        access = StoredMcpAccessToken(
            token=access_token,
            cartesia_credential=cartesia_credential,
            client_id=client_id,
            scopes=scopes,
            expires_at=access_expires_at,
            cartesia_admin_credential=cartesia_admin_credential,
            refresh_token=refresh_token,
        )
        refresh = StoredMcpRefreshToken(
            token=refresh_token,
            cartesia_credential=cartesia_credential,
            client_id=client_id,
            scopes=scopes,
            expires_at=refresh_expires_at,
            cartesia_admin_credential=cartesia_admin_credential,
            access_token=access_token,
        )
        self._backend.set_json(
            f"{_KEY_ACCESS}{access_token}",
            _access_to_dict(access),
            ttl_seconds=ACCESS_TOKEN_TTL_SECONDS,
        )
        self._backend.set_json(
            f"{_KEY_REFRESH}{refresh_token}",
            _refresh_to_dict(refresh),
            ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
        )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh_token,
        )

    def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        # Atomic pop so concurrent exchanges cannot both mint token pairs.
        creds = self._backend.pop_json(f"{_KEY_CODE_CREDENTIALS}{authorization_code.code}")
        self._backend.delete(f"{_KEY_AUTH_CODE}{authorization_code.code}")
        if creds is None:
            raise ValueError("Authorization code not found")
        if creds.get("client_id") != client.client_id:
            raise ValueError("Authorization code not found")

        return self._issue_token_pair(
            client_id=client.client_id,
            scopes=list(creds.get("scopes") or authorization_code.scopes or []),
            cartesia_credential=creds["cartesia_credential"],
            cartesia_admin_credential=creds.get("cartesia_admin_credential"),
        )

    def resolve_mcp_access_token(self, token: str) -> StoredMcpAccessToken | None:
        data = self._backend.get_json(f"{_KEY_ACCESS}{token}")
        if data is None:
            return None
        stored = _access_from_dict(data)
        if stored.expires_at < int(time.time()):
            return None
        return stored

    def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        data = self._backend.get_json(f"{_KEY_REFRESH}{refresh_token}")
        if data is None:
            return None
        stored = _refresh_from_dict(data)
        if stored.client_id != client.client_id:
            return None
        if stored.expires_at < int(time.time()):
            return None
        return RefreshToken(
            token=stored.token,
            client_id=stored.client_id,
            scopes=stored.scopes,
            expires_at=stored.expires_at,
        )

    def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        # Atomic pop so concurrent refreshes cannot both mint token pairs.
        data = self._backend.pop_json(f"{_KEY_REFRESH}{refresh_token.token}")
        if data is None:
            raise ValueError("Refresh token not found")
        stored = _refresh_from_dict(data)
        if stored.client_id != client.client_id:
            raise ValueError("Refresh token not found")
        if stored.expires_at < int(time.time()):
            raise ValueError("Refresh token expired")

        requested_scopes = scopes or stored.scopes
        if not set(requested_scopes).issubset(set(stored.scopes or requested_scopes)):
            raise ValueError("Requested scopes exceed granted scopes")

        if stored.access_token:
            self._backend.delete(f"{_KEY_ACCESS}{stored.access_token}")

        return self._issue_token_pair(
            client_id=client.client_id,
            scopes=list(requested_scopes),
            cartesia_credential=stored.cartesia_credential,
            cartesia_admin_credential=stored.cartesia_admin_credential,
        )

    def revoke_token(self, token: str) -> None:
        access = self._backend.get_json(f"{_KEY_ACCESS}{token}")
        if access is not None:
            stored = _access_from_dict(access)
            self._backend.delete(f"{_KEY_ACCESS}{token}")
            if stored.refresh_token:
                self._backend.delete(f"{_KEY_REFRESH}{stored.refresh_token}")
            return

        refresh = self._backend.get_json(f"{_KEY_REFRESH}{token}")
        if refresh is not None:
            stored_refresh = _refresh_from_dict(refresh)
            self._backend.delete(f"{_KEY_REFRESH}{token}")
            if stored_refresh.access_token:
                self._backend.delete(f"{_KEY_ACCESS}{stored_refresh.access_token}")


def configure_oauth_store_from_env(
    *,
    hosted: bool,
    redis_url: str | None,
) -> OAuthStore:
    """Configure the module singleton; fail closed when hosted without Redis."""
    if hosted:
        if not redis_url:
            raise RuntimeError(
                "REDIS_URL is required when MCP_HOSTED=1 "
                "(hosted MCP OAuth state must persist across deploys)"
            )
        oauth_store.use_backend(RedisBackend(redis_url))
    else:
        oauth_store.use_backend(MemoryBackend())
    return oauth_store


oauth_store = OAuthStore()
