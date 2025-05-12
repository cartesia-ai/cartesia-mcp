## Cartesia MCP Server

This is the official Cartesia MCP server which allows other MCP clients such as OpenAI agents, Curso and Claude Desktop to perform text to speech, transcribe audio, localize spech etc. 

### Cartesia Setup

Ensure that you have created an account on Cartesia and gotten your API key. There is a free tier with 10,000 credits per month.

### Installation

Install the python package using `pip install cartesia-mcp` 

Add the following to your MCP settings file such as `claude_desktop_config.json` 

```
{
  "mcpServers": {
    "cartesia-mcp": {
      "command": "uvx",
      "args": ["cartesia-mcp"],
      "env": {
        "CARTESIA_API_KEY": "<insert-your-api-key-here>",
        "OUTPUT_DIRECTORY": // directory to store generated files
      }
    }
  }
}
```

### Running From Source

- Clone this repo 

```
git clone https://github.com/cartesia-ai/cartesia-mcp.git
```

- Create a virtual enviornment and install all needed dependencies

```
cd cartesia-mcp
uv venv
source ./venv/bin/activate
uv pip install .
```