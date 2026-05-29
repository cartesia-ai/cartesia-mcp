# Cartesia MCP Server

[![PyPI version](https://img.shields.io/pypi/v/cartesia-mcp)](https://pypi.org/project/cartesia-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/cartesia-mcp)](https://pypi.org/project/cartesia-mcp/)

The Cartesia MCP server exposes [Cartesia](https://cartesia.ai/) APIs over the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) so clients such as **Cursor**, **Claude Desktop**, and **OpenAI Agents** can list voices, run **TTS**, clone voices, infill audio, and more—without one-off scripts.

**Documentation:** [Cartesia docs — MCP](https://docs.cartesia.ai/tools/ai/mcp) (overview and links back to this README).

## Requirements

- **Python 3.13+** (required; enforced in [`pyproject.toml`](./pyproject.toml))
- A **[Cartesia API key](https://play.cartesia.ai/keys)** — create one under **API Keys** after signing in at the [playground](https://play.cartesia.ai/sign-in). Free tier includes 20,000 credits per month.

## Installation

### pip

```sh
pip install cartesia-mcp
which cartesia-mcp   # copy absolute path for MCP config below
```

### uv (recommended for ephemeral runs)

If you use [uv](https://docs.astral.sh/uv/), you can run the published package without a global install:

```sh
uvx cartesia-mcp
```

Use `which uvx` or `command -v uvx` if your MCP client needs an absolute path to `uvx`. Some clients invoke MCP via `command` + `args` (see [Cursor](#cursor-integration)).

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `CARTESIA_API_KEY` | Yes | Your Cartesia API key |
| `OUTPUT_DIRECTORY` | No | Directory for generated audio files (defaults to `.`) |

## Claude Desktop integration

Edit **Settings → Developer → Edit Config** (`claude_desktop_config.json`).

Use either the **installed executable** (from `pip install`) or **`uvx`**:

### Installed `cartesia-mcp`

```json
{
  "mcpServers": {
    "cartesia-mcp": {
      "command": "/absolute/path/to/cartesia-mcp",
      "env": {
        "CARTESIA_API_KEY": "<your-api-key>",
        "OUTPUT_DIRECTORY": "/absolute/path/to/output"
      }
    }
  }
}
```

Omit `OUTPUT_DIRECTORY` to write files to the process working directory.

### uvx

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

### Try asking Claude to…

- List all available Cartesia voices
- Convert text to audio with a chosen voice
- Localize an existing voice into another language
- Infill audio between two segments (provide absolute paths to audio files)
- Change an audio file to use a different voice

## Cursor integration

Create **`.cursor/mcp.json`** in your project or **`~/.cursor/mcp.json`** globally.

### Installed `cartesia-mcp`

```json
{
  "mcpServers": {
    "cartesia-mcp": {
      "command": "/absolute/path/to/cartesia-mcp",
      "env": {
        "CARTESIA_API_KEY": "<your-api-key>",
        "OUTPUT_DIRECTORY": "/absolute/path/to/output"
      }
    }
  }
}
```

### uvx

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
