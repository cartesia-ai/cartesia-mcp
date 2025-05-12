# Cartesia MCP Server

The Cartesia MCP server provides a way for clients such as Cursor, Claude Desktop, and OpenAI agents to interact with Cartesia's API. Users can localize speech, convert text to audio, infill voice clips etc. 

## Cartesia Setup 

Ensure that you have created an account on [Cartesia](https://play.cartesia.ai/sign-in), there is a free tier with 20,000 credits per month. Once in the Cartesia playground, create an API key under API Keys --> New.

## Installation

```sh
pip install cartesia-mcp
which cartesia-mcp # absolute path to executable
```

## Claude Desktop Integration

Add the following to `claude_desktop_config.json` which can be found through Settings --> Developer --> Edit Config.

```
{
  "mcpServers": {
    "cartesia-mcp": {
      "command": "<absolute-path-to-executable>",
      "env": {
        "CARTESIA_API_KEY": "<insert-your-api-key-here>",
        "OUTPUT_DIRECTORY": // directory to store generated files (optional)
      }
    }
  }
}
```

Try asking Claude to 
- List all available Cartesia voices
- To convert a text phrase into audio using a particular voice
- To localize an existing voice into a different language
- To infill audio between two existing audio segments (specify absolute paths to audio files)
- To change an audio file to use a different voice

## Cursor Integration

Create either a `.cursor/mcp.json` in your project or a global `~/.cursor/mcp.json`. The same config as for Claude can be used. 
