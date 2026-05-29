# Cartesia MCP Server

[![PyPI version](https://img.shields.io/pypi/v/cartesia-mcp)](https://pypi.org/project/cartesia-mcp/)

The Cartesia MCP server exposes [Cartesia](https://cartesia.ai/) APIs over the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) so clients such as **Cursor**, **Claude Desktop**, and **OpenAI Agents** can list voices, run **TTS**, clone voices, infill audio, and more—without one-off scripts.

**Documentation:** [Cartesia docs — MCP](https://docs.cartesia.ai/tools/ai/mcp)

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — runs the server via `uvx` with no global install
- **Python 3.13+** (installed automatically by `uvx`)
- A **[Cartesia API key](https://play.cartesia.ai/keys)**

## Setup

Add this to your MCP config. You only need your API key.

**Cursor** — `.cursor/mcp.json` in your project, or `~/.cursor/mcp.json` globally.

**Claude Desktop** — **Settings → Developer → Edit Config** (`claude_desktop_config.json`).

```json
{
  "mcpServers": {
    "cartesia-mcp": {
      "command": "uvx",
      "args": ["cartesia-mcp"],
      "env": {
        "CARTESIA_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

Restart the client (or refresh MCP in Cursor) and confirm **cartesia-mcp** is connected.

## Try it

Ask your agent things like:

- List all available Cartesia voices
- Convert text to audio with a chosen voice
- Localize an existing voice into another language
- Infill audio between two existing audio segments
- Change an audio file to use a different voice

## Tools

| Tool | Description |
|------|-------------|
| `text_to_speech` | Convert text to audio with a chosen voice and model |
| `list_voices` | List available voices (optionally filter by language or gender) |
| `get_voice` | Fetch metadata for a voice by ID |
| `clone_voice` | Clone a voice from an audio sample |
| `update_voice` | Update a cloned voice's name or description |
| `delete_voice` | Delete a cloned voice |
| `infill` | Generate audio between two existing audio segments |
| `voice_change` | Re-render audio with a different voice |
| `localize_voice` | Adapt a voice to another language or dialect |

See [`cartesia_mcp/server.py`](./cartesia_mcp/server.py) for parameters and return types.

## Testing

Smoke-test all tools (requires `CARTESIA_API_KEY`):

```sh
uv run python scripts/test_all_tools.py
```

The script creates temporary cloned/localized voices and deletes only those. It does not delete catalog or other existing voices.

## Advanced

### Output directory

By default, generated audio is written to the server's working directory. To choose a fixed folder, add `OUTPUT_DIRECTORY` to `env`:

```json
"env": {
  "CARTESIA_API_KEY": "<your-api-key>",
  "OUTPUT_DIRECTORY": "~/cartesia-output"
}
```

### Local audio files

Tools like `infill` and `voice_change` need paths to existing audio files on disk. Pass the full path to each file when prompting your agent.
