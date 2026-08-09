import asyncio
import os
import json
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def run():
    params = StdioServerParameters(
        command="cmd",
        args=["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "d:/projs/deepseek/deepseek4free"],
        env=os.environ.copy()
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            
            # Call edit_file
            tool_name = "edit_file"
            args = {
                "path": "d:/projs/deepseek/deepseek4free/main_cli.py",
                "edits": [
                    {
                        "oldText": "def format_upload_error(e: Exception) -> str:\n    \"\"\"Turn a raw upload exception into something actionable instead of a bare repr.\"\"\"",
                        "newText": "def format_upload_error(e: Exception) -> str:\n    \"\"\"Fixed\"\"\""
                    }
                ]
            }
            try:
                res = await session.call_tool(tool_name, args)
                print("Result:")
                print(res)
            except Exception as e:
                print("Error:")
                print(e)

if __name__ == "__main__":
    asyncio.run(run())
