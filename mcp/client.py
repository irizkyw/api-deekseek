import os
import sys
import json
import asyncio
import threading
from typing import Dict, Any, List, Tuple
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

class MCPManager:
    """
    Manages connections to stdio MCP servers configured in Claude Desktop config.
    Runs an internal asyncio event loop in a background thread to handle stdio communication.
    """
    def __init__(self, config_path: str = None):
        if not config_path:
            # Try to locate Claude Desktop config
            appdata = os.getenv("APPDATA", "")
            if appdata:
                config_path = os.path.join(appdata, "Claude", "claude_desktop_config.json")
            else:
                config_path = ""
                
        self.config_path = config_path
        self.sessions: Dict[str, ClientSession] = {}
        self.transports = []  # keep references to prevent garbage collection
        self.tools: Dict[str, Tuple[str, Any]] = {}  # {tool_name: (server_name, tool_obj)}
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coro(self, coro):
        """Helper to run a coroutine in the background thread's event loop and wait for result."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result()

    def load_servers(self) -> List[str]:
        """Loads and initializes configured stdio MCP servers. Returns list of active server names."""
        if not self.config_path or not os.path.exists(self.config_path):
            return []

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            return []

        mcp_servers = config.get("mcpServers", {})
        active_servers = []

        for name, cfg in mcp_servers.items():
            # Skip ourselves to avoid infinite loops/self-calling
            if "deepseek-free" in name:
                continue

            command = cfg.get("command")
            args = list(cfg.get("args", []))
            
            # If it is the filesystem server, dynamically add current project directory
            if name == "filesystem":
                cwd = os.getcwd().replace("\\", "/")
                if not any(cwd.lower() in str(arg).lower().replace("\\", "/") for arg in args):
                    args.append(cwd)

            env = os.environ.copy()
            # Merge configured environment variables
            if cfg.get("env"):
                env.update(cfg.get("env"))

            if not command:
                continue

            try:
                self.run_coro(self._connect_server(name, command, args, env))
                active_servers.append(name)
            except Exception as e:
                print(f"Failed to connect to MCP server {name}: {e}")

        # Refresh tool list after loading servers
        self.refresh_tools()
        return active_servers

    async def _connect_server(self, name: str, command: str, args: List[str], env: Dict[str, str]):
        params = StdioServerParameters(command=command, args=args, env=env)
        # We need to maintain the stdio transport context manager
        transport_ctx = stdio_client(params)
        read_stream, write_stream = await transport_ctx.__aenter__()
        
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()
        
        self.sessions[name] = session
        self.transports.append((transport_ctx, session))

    def refresh_tools(self):
        """Fetches the list of tools from all connected servers."""
        new_tools = {}
        for name, session in self.sessions.items():
            try:
                tools_result = self.run_coro(session.list_tools())
                for t in tools_result.tools:
                    new_tools[t.name] = (name, t)
            except Exception as e:
                print(f"Error fetching tools from {name}: {e}")
        self.tools = new_tools

    def get_system_prompt(self) -> str:
        """Generates a system prompt to guide DeepSeek on how to use the available tools."""
        if not self.tools:
            return ""

        prompt = (
            "\n\n=== SYSTEM INSTRUCTION: LOCAL TOOLS AVAILABLE ===\n"
            "You have access to the following local tools on the user's system via MCP:\n"
        )
        
        for name, (server, t) in self.tools.items():
            prompt += f"- Tool: {t.name} (Server: {server})\n"
            prompt += f"  Description: {t.description}\n"
            # Format arguments/schema simply
            schema = getattr(t, "inputSchema", {})
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            if properties:
                prompt += "  Parameters:\n"
                for param, pcfg in properties.items():
                    req_star = "*" if param in required else ""
                    prompt += f"    - {param}{req_star} ({pcfg.get('type', 'any')}): {pcfg.get('description', '')}\n"
            prompt += "\n"

        prompt += (
            "CRITICAL DIRECTIVE: You are an agentic coding assistant with full read/write file system access. "
            "If the user asks you to fix a bug, optimize code, implement features, or make changes, you MUST "
            "proactively write or edit the files yourself using the 'edit_file' or 'write_file' tools. "
            "Do NOT just write explanations or show code blocks in your text response. DIRECTLY execute the tools "
            "to modify the files on disk immediately. Be bold, active, and implement fixes directly.\n\n"
            "To call a tool, you MUST output a single valid JSON block containing the keys "
            "\"tool\" and \"arguments\". The block MUST start exactly with ```json and end with ```. "
            "Example format:\n"
            "```json\n"
            "{\n"
            "  \"tool\": \"read_text_file\",\n"
            "  \"arguments\": {\n"
            "    \"path\": \"C:/docs/file.txt\"\n"
            "  }\n"
            "}\n"
            "```\n"
            "When you output a tool call block, do NOT generate any other text after it. "
            "Wait for the tool result which will be provided as context in the next turn.\n"
            "==================================================\n"
        )
        return prompt

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Executes a tool on the target MCP server."""
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' is not registered."

        # Auto-correct common LLM argument naming mistakes for edit_file
        if tool_name == "edit_file" and isinstance(arguments, dict):
            edits = arguments.get("edits", [])
            if isinstance(edits, list):
                for item in edits:
                    if isinstance(item, dict):
                        # Map old/old_text -> oldText
                        if "old" in item and "oldText" not in item:
                            item["oldText"] = item.pop("old")
                        if "old_text" in item and "oldText" not in item:
                            item["oldText"] = item.pop("old_text")
                        
                        # Map new/new_text -> newText
                        if "new" in item and "newText" not in item:
                            item["newText"] = item.pop("new")
                        if "new_text" in item and "newText" not in item:
                            item["newText"] = item.pop("new_text")

                        # Ensure both are strings and present to avoid Zod schema validation errors
                        if "oldText" not in item or item["oldText"] is None:
                            item["oldText"] = ""
                        if "newText" not in item or item["newText"] is None:
                            item["newText"] = ""

        server_name, _ = self.tools[tool_name]
        session = self.sessions.get(server_name)
        if not session:
            return f"Error: Session for server '{server_name}' is lost."

        try:
            result = self.run_coro(session.call_tool(tool_name, arguments))
            
            # Format text contents of the response
            output_parts = []
            for content in result.content:
                if content.type == "text":
                    output_parts.append(content.text)
                elif content.type == "image":
                    output_parts.append(f"[Image content generated: {content.mimeType}]")
            return "\n".join(output_parts)
        except Exception as e:
            return f"Error executing tool '{tool_name}': {e}"

    def close(self):
        """Closes all connected MCP server sessions."""
        for _, session in self.transports:
            try:
                self.run_coro(session.__aexit__(None, None, None))
            except Exception:
                pass
        for ctx, _ in self.transports:
            try:
                self.run_coro(ctx.__aexit__(None, None, None))
            except Exception:
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)
