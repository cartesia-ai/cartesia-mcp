"""The FastMCP instance, its config side effects, and shared tool helpers."""

import sys
import typing

from cartesia import Cartesia
from dotenv import load_dotenv
from mcp.types import ToolAnnotations

from cartesia_mcp import __version__
from cartesia_mcp.branding import (
    SERVER_DESCRIPTION,
    SERVER_INSTRUCTIONS,
    SERVER_NAME,
    WEBSITE_URL,
    server_icons,
)
from cartesia_mcp.clients import client, require_admin_client
from cartesia_mcp.config import env_or_none, validate_api_keys
from cartesia_mcp.credentials import (
    configure_hosted_mode,
    configure_stdio_credentials,
)
from cartesia_mcp.hosted import (
    configure_hosted_oauth_store,
    hosted_enabled,
    hosted_server_kwargs,
    server_public_url,
)
from cartesia_mcp.mcpserver import CartesiaMCP
from cartesia_mcp.utils import (
    default_output_directory,
)

load_dotenv()

_is_hosted = hosted_enabled() or (
    "--transport" in sys.argv and "streamable-http" in sys.argv
)
CARTESIA_API_KEY, CARTESIA_ADMIN_API_KEY = validate_api_keys(
    env_or_none("CARTESIA_API_KEY"),
    env_or_none("CARTESIA_ADMIN_API_KEY"),
    require_api_key=not _is_hosted,
)

OUTPUT_DIRECTORY = default_output_directory(hosted=_is_hosted)

if _is_hosted:
    configure_hosted_mode()
    if hosted_enabled():
        configure_hosted_oauth_store()
elif CARTESIA_API_KEY:
    configure_stdio_credentials(CARTESIA_API_KEY, CARTESIA_ADMIN_API_KEY)

mcp = CartesiaMCP(
    SERVER_NAME,
    description=SERVER_DESCRIPTION,
    instructions=SERVER_INSTRUCTIONS,
    website_url=WEBSITE_URL,
    icons=server_icons(origin=server_public_url() if _is_hosted else None),
    version=__version__,
    **(hosted_server_kwargs() if _is_hosted else {}),
)

# Account-scoped tools are closed-world; arbitrary webhook destinations and
# real phone network actions are open-world.
def _read_only_tool(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )


def _additive_tool(title: str, *, open_world: bool = False) -> ToolAnnotations:
    return ToolAnnotations(
        title=title, read_only_hint=False, destructive_hint=False, open_world_hint=open_world
    )


def _real_world_tool(title: str) -> ToolAnnotations:
    """Dials real phone numbers or buys one. Not undoable, so clients should ask first."""
    return ToolAnnotations(
        title=title,
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=True,
    )


def _destructive_tool(
    title: str, *, idempotent: bool = True, open_world: bool = False
) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


def _require_admin_client() -> Cartesia:
    return require_admin_client()


def _api_client() -> Cartesia:
    return typing.cast(Cartesia, client)



