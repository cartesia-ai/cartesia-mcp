# Cartesia MCP Server

[![PyPI version](https://img.shields.io/pypi/v/cartesia-mcp)](https://pypi.org/project/cartesia-mcp/)

The Cartesia MCP server exposes [Cartesia](https://cartesia.ai/) APIs over the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) so clients such as **Cursor**, **Claude Desktop**, and **OpenAI Agents** can list voices, run **TTS** and **STT**, manage pronunciation dictionaries, clone voices, and more—without one-off scripts.

**Documentation:** [Cartesia docs — MCP](https://docs.cartesia.ai/tools/ai/mcp)

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — runs the server via `uvx` with no global install
- **Python 3.13+** (installed automatically by `uvx`)
- A **[Cartesia API key](https://play.cartesia.ai/keys)** for TTS, STT, voices, and related APIs
- Optionally, an **[admin API key](https://play.cartesia.ai/keys)** (Keys → Admin) for management tools such as `get_credit_usage`. Admin keys and standard keys are separate credentials; each only works on its own route class.

## Setup

Get an [API key](https://play.cartesia.ai/keys). Full instructions: [Cartesia docs — MCP](https://docs.cartesia.ai/tools/ai/mcp).

**CLI (recommended)** — `npx add-mcp "uvx cartesia-mcp" --name cartesia-mcp --env 'CARTESIA_API_KEY=${CARTESIA_API_KEY}'`

**Cursor** — [Install Cartesia MCP](cursor://anysphere.cursor-deeplink/mcp/install?name=cartesia-mcp&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJjYXJ0ZXNpYS1tY3AiXX0=), then set `CARTESIA_API_KEY` in **Settings → MCP**.

**Claude Code** — `claude mcp add -e CARTESIA_API_KEY=<your-api-key> cartesia-mcp -- uvx cartesia-mcp`

## Manual setup

Add to `.cursor/mcp.json`, `.mcp.json` (Claude Code), or your client’s MCP config:

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

## Try it

Ask your agent things like:

- List all available Cartesia voices
- Convert text to audio with a chosen voice (speed, volume, emotion)
- Transcribe an audio file to text
- Create a pronunciation dictionary and use it in TTS
- Check credit usage for your account
- Localize an existing voice into another language
- Change an audio file to use a different voice

## Tools

| Tool | Description |
|------|-------------|
| `text_to_speech` | Convert text to audio; optional speed, volume, emotion, and pronunciation dict |
| `speech_to_text` | Transcribe an audio file (`mode=batch` default, or `mode=stream`) |
| `list_voices` | List available voices (filter by language, search, gender, etc.) |
| `get_voice` | Fetch metadata for a voice by ID |
| `clone_voice` | Clone a voice from an audio sample |
| `update_voice` | Update a cloned voice's name or description |
| `delete_voice` | Delete a cloned voice |
| `voice_change` | Re-render audio with a different voice |
| `localize_voice` | Adapt a voice to another language or dialect |
| `list_pronunciation_dicts` | List pronunciation dictionaries |
| `create_pronunciation_dict` | Create a pronunciation dictionary |
| `get_pronunciation_dict` | Get a pronunciation dictionary by ID |
| `update_pronunciation_dict` | Update a pronunciation dictionary |
| `delete_pronunciation_dict` | Delete a pronunciation dictionary |
| `get_credit_usage` | Credit usage over time (`CARTESIA_ADMIN_API_KEY`) |

See [`cartesia_mcp/server.py`](./cartesia_mcp/server.py) for parameters and return types.

## Releases

Versions and PyPI publishes are driven by [Conventional Commits](https://www.conventionalcommits.org/) on `main` via release-please. Use PR titles like `feat: …` or `fix: …` (especially when squash merging). See [CONTRIBUTING.md](./CONTRIBUTING.md).

## Testing

Unit tests (no API keys):

```sh
uv sync --dev
uv run pytest
```

Smoke-test all tools (requires `CARTESIA_API_KEY`):

```sh
uv run python scripts/test_all_tools.py
```

The script creates temporary cloned/localized voices and pronunciation dictionaries, then deletes only those. It does not delete catalog or other existing resources.

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

Tools like `speech_to_text` and `voice_change` need paths to existing audio files on disk. Pass the full path to each file when prompting your agent. For `speech_to_text`, use the default batch mode for common containers (mp3, flac, wav, etc.). Use `mode="stream"` for mono PCM WAV or raw PCM with `encoding` and `sample_rate`.

### Admin API key

Some tools call [management endpoints](https://docs.cartesia.ai/api-reference/usage/credits) that accept **admin** API keys only (`sk_car_admin_...`). Set `CARTESIA_ADMIN_API_KEY` in `env` alongside `CARTESIA_API_KEY`:

- `CARTESIA_API_KEY` — TTS, STT, voices, pronunciation dictionaries, voice changer, etc.
- `CARTESIA_ADMIN_API_KEY` — optional; required for `get_credit_usage` today. Admin keys do not work on generation routes, and standard keys do not work on admin routes.

Mint admin keys in the Playground under **Keys → Admin** (org admins only).

### API version

All tools send `Cartesia-Version` (default `2026-03-01`, the latest in [Cartesia docs](https://docs.cartesia.ai/use-the-api/api-conventions)). Override with `CARTESIA_VERSION` in `env` if you pin an older integration date.
