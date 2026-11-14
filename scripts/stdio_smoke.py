#!/usr/bin/env python3
"""Start a cartesia-mcp command over stdio and check it initializes and lists tools and prompts.

No API calls are made, so any non-admin CARTESIA_API_KEY works.

    uv run python scripts/stdio_smoke.py uvx --from dist/cartesia_mcp-*.whl cartesia-mcp
"""

from __future__ import annotations

import asyncio
import os
import sys
import tomllib
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_PROMPTS = {"generate_and_transcribe", "clone_and_localize"}


async def main(command: list[str]) -> None:
    version = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())[
        "project"
    ]["version"]
    env = {"CARTESIA_API_KEY": "sk_car_smoke", **os.environ}
    params = StdioServerParameters(command=command[0], args=command[1:], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = (await session.list_tools()).tools
            prompts = {p.name for p in (await session.list_prompts()).prompts}

    print(f"{init.server_info.name} {init.server_info.version}: "
          f"{len(tools)} tools, prompts {sorted(prompts)}")
    assert init.server_info.version == version, f"expected version {version}"
    assert len(tools) >= 15, "expected the standard tool set"
    assert all(t.input_schema.get("type") == "object" for t in tools)
    assert EXPECTED_PROMPTS <= prompts, f"missing prompts {EXPECTED_PROMPTS - prompts}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1:]))
