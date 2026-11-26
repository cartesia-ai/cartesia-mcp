"""Shared helpers for hosted Streamable HTTP /mcp middleware."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from starlette.requests import Request

from cartesia_mcp.register_rate_limit import client_ip

_MAX_RPC_METHOD_LEN = 64
_MAX_CLIENT_INFO_LEN = 100
_MAX_USER_AGENT_LEN = 200
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_CLIENT_INFO_SAFE = re.compile(r"[\x00-\x1f\x7f]")


def is_mcp_path(path: str) -> bool:
    return path.rstrip("/") == "/mcp"


def opens_legacy_mcp_session(request: Request) -> bool:
    """True when this request can mint an Mcp-Session-Id.

    Streamable HTTP routes on MCP-Protocol-Version. A header outside the
    handshake-era versions is served statelessly and never opens a session.
    A missing header, or a 2024/2025 handshake version, still does.
    """
    version = request.headers.get(MCP_PROTOCOL_VERSION_HEADER)
    if version is None:
        return True
    return version in HANDSHAKE_PROTOCOL_VERSIONS


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    return token or None


def jsonrpc_method_from_body(body: bytes) -> str | None:
    message = _first_jsonrpc_message(body)
    if message is None:
        return None
    method = message.get("method")
    if not isinstance(method, str) or not method or len(method) > _MAX_RPC_METHOD_LEN:
        return None
    return method


def _first_jsonrpc_message(body: bytes) -> dict | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return None


def jsonrpc_tool_name_from_body(body: bytes) -> str | None:
    """Tool name on a tools/call request. Other methods and unsafe names are omitted."""
    message = _first_jsonrpc_message(body)
    if message is None or message.get("method") != "tools/call":
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    name = params.get("name")
    if not isinstance(name, str) or _TOOL_NAME.fullmatch(name) is None:
        return None
    return name


@dataclass(frozen=True)
class McpClientInfo:
    name: str
    version: str | None = None


def _sanitize_client_info_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _CLIENT_INFO_SAFE.sub("", value).strip()
    if not cleaned:
        return None
    return cleaned[:_MAX_CLIENT_INFO_LEN]


def jsonrpc_client_info_from_body(body: bytes) -> McpClientInfo | None:
    """Host clientInfo from an initialize request. Other methods are omitted."""
    message = _first_jsonrpc_message(body)
    if message is None or message.get("method") != "initialize":
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    info = params.get("clientInfo")
    if not isinstance(info, dict):
        return None
    name = _sanitize_client_info_field(info.get("name"))
    if name is None:
        return None
    return McpClientInfo(
        name=name,
        version=_sanitize_client_info_field(info.get("version")),
    )


def redirect_fingerprint(uri: object) -> str | None:
    """Scheme + host (or custom-scheme authority) for OAuth redirect_uris."""
    if uri is None:
        return None
    raw = str(uri).strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.scheme:
        return None
    if parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"[:_MAX_USER_AGENT_LEN]
    path = parsed.path.lstrip("/")
    authority = path.split("/", 1)[0] if path else ""
    if authority:
        return f"{parsed.scheme}://{authority}"[:_MAX_USER_AGENT_LEN]
    return parsed.scheme[:64]


def request_user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent")
    if not value:
        return None
    cleaned = _CLIENT_INFO_SAFE.sub("", value).strip()
    if not cleaned:
        return None
    return cleaned[:_MAX_USER_AGENT_LEN]


def request_protocol_version(request: Request) -> str | None:
    value = request.headers.get(MCP_PROTOCOL_VERSION_HEADER)
    if not isinstance(value, str) or not value:
        return None
    cleaned = _CLIENT_INFO_SAFE.sub("", value).strip()
    if not cleaned or len(cleaned) > 32:
        return None
    return cleaned


def mcp_credential_key(request: Request) -> str | None:
    """Stable hashed bearer key for per-credential maps. None when unauthenticated."""
    import hashlib

    token = bearer_token(request)
    if token is None:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"tok:{digest}"


def mcp_rate_limit_bucket(request: Request) -> str:
    """Prefer a hashed bearer so shared egress IPs do not share one bucket."""
    key = mcp_credential_key(request)
    if key is not None:
        return key
    return f"ip:{client_ip(request)}"
