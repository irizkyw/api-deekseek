import asyncio
import os
import json
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def test_connect():
    # Test connecting to the filesystem server
    # args from config: ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:/Users/Lenovo-15IRX9/Documents/Obsidian Vault"]
    params = StdioServerParameters(
        command="cmd",
        args=["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:/Users/Lenovo-15IRX9/Documents/Obsidian Vault"],
        env=os.environ.copy()
    )
    
    print("Connecting to filesystem MCP server...")
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Successfully initialized session!")
            
            # List tools
            tools = await session.list_tools()
            print("Available tools:")
            for t in tools.tools:
                print(f"- {t.name}: {t.description}")

if __name__ == "__main__":
    asyncio.run(test_connect())
