"""Resolve Cartesia API credentials for stdio vs hosted MCP."""

from __future__ import annotations

from contextvars import ContextVar

from cartesia_mcp.config import env_or_none
from cartesia_mcp.sdk_setup import is_admin_api_key

_stdio_api_key: str | None = None
_stdio_admin_api_key: str | None = None
_hosted_admin_credential: ContextVar[str | None] = ContextVar(
    "hosted_admin_credential",
    default=None,
)


def configure_stdio_credentials(
    api_key: str,
    admin_api_key: str | None,
) -> None:
    global _stdio_api_key, _stdio_admin_api_key
    _stdio_api_key = api_key
    _stdio_admin_api_key = admin_api_key


def set_hosted_admin_credential(admin_credential: str | None) -> None:
    _hosted_admin_credential.set(admin_credential)


def resolve_api_credential() -> str:
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        access = get_access_token()
        if access is not None and access.token:
            return access.token
    except ImportError:
        pass

    if _stdio_api_key:
        return _stdio_api_key

    raise ValueError(
        "No Cartesia credential. Set CARTESIA_API_KEY for stdio, or authenticate "
        "via bearer token / OAuth for hosted MCP."
    )


def resolve_admin_api_credential() -> str | None:
    hosted_admin = _hosted_admin_credential.get()
    if hosted_admin:
        return hosted_admin
    if _stdio_admin_api_key:
        return _stdio_admin_api_key
    return None


def looks_like_cartesia_api_key(token: str) -> bool:
    return token.startswith("sk_car_") and not token.startswith("sk_car_admin_")


def looks_like_cartesia_access_token(token: str) -> bool:
    return token.startswith("eyJ")


def is_valid_bearer_credential(token: str) -> bool:
    if looks_like_cartesia_api_key(token):
        return not is_admin_api_key(token)
    return looks_like_cartesia_access_token(token)
