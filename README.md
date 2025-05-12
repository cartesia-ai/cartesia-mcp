## Cartesia MCP Server

This is the official Cartesia MCP server which allows other MCP clients such as OpenAI agents, Curso and Claude Desktop to perform text to speech, transcribe audio, localize spech etc. 

### Cartesia Setup

Ensure that you have created an account on Cartesia and gotten your API key. There is a free tier with 20,000 credits per month.

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

Try asking Claude to 
- list all feminine, masculine, or gender neutral Cartesia voices
- to provide more information about voice X
- to convert a text phrase to audio using a particular voice
- to generate audio to connect two existing audio segments (specify file paths)
- to create a new voice from an existing voice
