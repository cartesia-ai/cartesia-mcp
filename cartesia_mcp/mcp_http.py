"""Shared helpers for hosted Streamable HTTP /mcp middleware."""

from __future__ import annotations

import json

from starlette.requests import Request

from cartesia_mcp.register_rate_limit import client_ip

_MAX_RPC_METHOD_LEN = 64


def is_mcp_path(path: str) -> bool:
    return path.rstrip("/") == "/mcp"


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token or None


def jsonrpc_method_from_body(body: bytes) -> str | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    method: object = None
    if isinstance(payload, dict):
        method = payload.get("method")
    elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
        method = payload[0].get("method")
    if not isinstance(method, str) or not method or len(method) > _MAX_RPC_METHOD_LEN:
        return None
    return method


def mcp_rate_limit_bucket(request: Request) -> str:
    """Prefer a hashed bearer so shared egress IPs do not share one bucket."""
    import hashlib

    token = bearer_token(request)
    if token is not None:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return f"tok:{digest}"
    return f"ip:{client_ip(request)}"
