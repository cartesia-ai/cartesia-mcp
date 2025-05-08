## Cartesia MCP Server

### Setup

- Get your API key from Cartesia. There is a free tier with 10,000 credits per month.
- Clone this repo via `git clone https://github.com/cartesia-ai/cartesia-mcp.git`
- Rename `.env.example` to `.env` and fill it in with your values
- Install uv (Python package manager) with `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Using Claude Desktop 

- Go to Claude > Settings > Developer > Edit Config > claude_desktop_config.json to include the following

```
{
  "mcpServers": {
    "cartesia-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/<ABSOLUTE-PATH-TO>/cartesia-mcp",
        "run",
        "src/server.py"
      ],
      "env": {
        "CARTESIA_API_KEY": "<insert-your-api-key-here>",
        "OUTPUT_DIRECTORY": // directory to store generated files
      }
    }
  }
}
```