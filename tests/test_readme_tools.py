"""README Tools table stays aligned with registered MCP tools.

Docs and marketing should link here instead of re-listing tools, so this
table is the public source of truth for tool names.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from cartesia_mcp import server

_README = Path(__file__).resolve().parents[1] / "README.md"
_TOOL_ROW = re.compile(r"^\| `([a-z][a-z0-9_]*)` \|", re.MULTILINE)


def _readme_tool_names() -> list[str]:
    readme = _README.read_text()
    section = readme.split("## Tools", 1)[1].split("## ", 1)[0]
    return _TOOL_ROW.findall(section)


def test_readme_tools_match_registered_tools(monkeypatch) -> None:
    monkeypatch.setattr(
        "cartesia_mcp.tool_visibility.resolve_admin_api_credential",
        lambda: "sk_car_admin_test.key",
    )
    registered = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    documented = _readme_tool_names()

    assert documented, "README ## Tools table has no tool rows"
    assert len(documented) == len(set(documented)), (
        "README Tools table has duplicate names"
    )
    assert set(documented) == registered, (
        f"README missing {sorted(registered - set(documented))}; "
        f"README extra {sorted(set(documented) - registered)}"
    )
