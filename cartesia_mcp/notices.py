"""Messages from Cartesia for the person behind the API key (GET /notices).

The backend decides who gets one, what it says and how often; this module only
asks now and then and hands the text to the coding agent with any tool result.
"""

from __future__ import annotations

import hashlib
import time
import typing

from mcp.types import CallToolResult, TextContent

from cartesia_mcp import extra_api
from cartesia_mcp.clients import client
from cartesia_mcp.credentials import resolve_api_credential

# Asked at most this often per API key; the backend sends any one notice at most
# a few times, a day apart.
NOTICE_CHECK_SECONDS = 15 * 60
_checked_at: dict[str, float] = {}


def account_notice() -> typing.Optional[str]:
    """This user's notice, if it's time to ask and there is one; None on any failure."""
    try:
        key = hashlib.sha256(resolve_api_credential().encode()).hexdigest()
    except Exception:
        return None
    now = time.monotonic()
    last = _checked_at.get(key)
    if last is not None and now - last < NOTICE_CHECK_SECONDS:
        return None
    if len(_checked_at) > 10_000:
        _checked_at.clear()
    _checked_at[key] = now
    try:
        return extra_api.get_account_notice(typing.cast(typing.Any, client))
    except Exception:
        return None


def with_notice(result: CallToolResult, notice: str) -> CallToolResult:
    """The tool's result with the notice added as its own text block for the agent to relay."""
    block = TextContent(
        type="text",
        text=f"Message from Cartesia for the user. Show it to them as written:\n{notice}",
    )
    return result.model_copy(update={"content": [*result.content, block]})
