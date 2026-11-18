"""Server identity and brand assets advertised to MCP clients."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from mcp.types import Icon

SERVER_NAME = "Cartesia"
SERVER_DESCRIPTION = "The official Cartesia MCP server"
WEBSITE_URL = "https://cartesia.ai"
PRODUCTION_MCP_ORIGIN = "https://mcp.cartesia.ai"
ICON_PATH = "/icon.png"
ICON_SVG_PATH = "/icon.svg"
ICON_SIZES = ["512x512"]
DOCS_URL = "https://docs.cartesia.ai/tools/ai/mcp"
PLAYGROUND_URL = "https://play.cartesia.ai"

SERVER_INSTRUCTIONS = """\
Cartesia speech (text to speech, speech to text, voices) and Managed Agents \
(hosted voice agents).

To build an agent from a description, write its instructions, pick a model \
from `list_agent_models` and a voice from `list_voices`, call `create_agent`, \
then share the returned `playground_url` so the user can talk to it.

To debug an agent, use `list_agent_calls` and `get_agent_call`, then \
`get_agent_version` with the call's `agent_version_id` to read the config that ran.

Transfers, ending calls, DTMF, and voicemail detection are `config.system_tools` \
on the agent. Custom actions are `create_agent_tool`, then the returned id goes \
in `config.tools`. Knowledge base folders and documents, event webhooks, and \
evaluation metrics each have their own tools; attach them through the agent's \
config or `attach_agent_metric`. Open the `playground_url` from `create_agent` \
to talk to the agent.

A tool that dials a person, sends a message, or buys a number needs the user to \
confirm the destination, the agent, and the number in this conversation first. \
Today those are `create_agent_calls`, `create_call_batch`, `retry_call_batch`, \
and `provision_phone_number`. Confirm the target before any update or delete \
as well.\
"""

STATIC_DIR = Path(__file__).resolve().parent / "static"
ICON_PNG_PATH = STATIC_DIR / "icon.png"
ICON_SVG_FILE = STATIC_DIR / "icon.svg"


def playground_agent_url(agent_id: str) -> str:
    return f"{PLAYGROUND_URL}/agents/{quote(agent_id, safe='')}"


def icon_url(origin: str | None = None, path: str = ICON_PATH) -> str:
    base = (origin or PRODUCTION_MCP_ORIGIN).rstrip("/")
    return f"{base}{path}"


def server_icons(*, origin: str | None = None) -> list[Icon]:
    return [
        Icon(
            src=icon_url(origin),
            mime_type="image/png",
            sizes=ICON_SIZES,
        ),
        Icon(
            src=icon_url(origin, ICON_SVG_PATH),
            mime_type="image/svg+xml",
            sizes=["any"],
        ),
    ]
