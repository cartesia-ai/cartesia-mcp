"""Environment and API key configuration for the MCP server."""

from __future__ import annotations

import os
import typing

from cartesia_mcp.sdk_setup import is_admin_api_key

ADMIN_HTTP_REQUIRED_MESSAGE = (
    "This tool requires CARTESIA_ADMIN_API_KEY. Admin keys are separate from "
    "standard API keys and only work on management endpoints (e.g. GET /usage/credits). "
    "Create one in the Playground under Keys → Admin."
)


def env_or_none(
    name: str,
    environ: typing.Mapping[str, str | None] | None = None,
) -> str | None:
    source = os.environ if environ is None else environ
    value = source.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def validate_api_keys(
    api_key: str | None,
    admin_api_key: str | None,
    *,
    require_api_key: bool = True,
) -> tuple[str | None, str | None]:
    if require_api_key and not api_key:
        raise ValueError("CARTESIA_API_KEY is required")

    if api_key is not None and is_admin_api_key(api_key):
        raise ValueError(
            "CARTESIA_API_KEY must be a standard API key (sk_car_...), not an admin key. "
            "Use CARTESIA_ADMIN_API_KEY for admin-only tools such as get_credit_usage."
        )

    if admin_api_key is not None and not is_admin_api_key(admin_api_key):
        raise ValueError(
            "CARTESIA_ADMIN_API_KEY must be an admin API key (sk_car_admin_...)."
        )

    return api_key, admin_api_key


def ensure_admin_client(admin_client: typing.Any) -> typing.Any:
    if admin_client is None:
        raise ValueError(ADMIN_HTTP_REQUIRED_MESSAGE)
    return admin_client
