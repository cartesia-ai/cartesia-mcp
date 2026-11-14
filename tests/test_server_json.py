"""server.json (MCP Registry metadata) must stay in sync with the package."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _server_json() -> dict:
    return json.loads((ROOT / "server.json").read_text())


def test_server_json_versions_match_pyproject() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    server = _server_json()
    assert server["version"] == version
    assert [pkg["version"] for pkg in server["packages"]] == [version]


def test_readme_has_registry_ownership_marker() -> None:
    name = _server_json()["name"]
    assert f"<!-- mcp-name: {name} -->" in (ROOT / "README.md").read_text()


def test_server_json_lists_hosted_remote() -> None:
    remotes = _server_json()["remotes"]
    assert {"type": "streamable-http", "url": "https://mcp.cartesia.ai/mcp"} in remotes
