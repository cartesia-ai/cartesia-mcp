"""Request-scoped Cartesia SDK clients."""

from __future__ import annotations

from cartesia import Cartesia

from cartesia_mcp.config import ADMIN_HTTP_REQUIRED_MESSAGE, ensure_admin_client
from cartesia_mcp.credentials import resolve_admin_api_credential, resolve_api_credential
from cartesia_mcp.sdk_setup import create_cartesia_client


def get_client() -> Cartesia:
    return create_cartesia_client(resolve_api_credential())


def get_admin_client() -> Cartesia:
    admin_key = resolve_admin_api_credential()
    if admin_key is None:
        raise ValueError(ADMIN_HTTP_REQUIRED_MESSAGE)
    return create_cartesia_client(admin_key)


def require_admin_client() -> Cartesia:
    admin_key = resolve_admin_api_credential()
    return ensure_admin_client(
        create_cartesia_client(admin_key) if admin_key else None
    )


class _CartesiaClientProxy:
    def __getattr__(self, name: str):
        if name == "__func__":
            raise AttributeError(name)
        return getattr(get_client(), name)


class _AdminClientProxy:
    def __getattr__(self, name: str):
        if name == "__func__":
            raise AttributeError(name)
        return getattr(require_admin_client(), name)


client = _CartesiaClientProxy()
admin_client = _AdminClientProxy()
