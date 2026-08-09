"""
DeepSeek Free MCP Server
Provides Model Context Protocol (MCP) access to DeepSeek's unofficial web chat API,
supporting free chats, thinking mode (DeepSeek-R1), web search, and image uploads.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional, List
from dotenv import load_dotenv

# Add current directory to Python path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from mcp.server.fastmcp import FastMCP
from deepseek_api import DeepSeekAPI, AuthenticationError, RateLimitError, NetworkError, APIError

load_dotenv()

# Initialize FastMCP server
mcp = FastMCP(
    "DeepSeek Free",
    version="1.0.0",
    dependencies=["mcp", "curl_cffi", "wasmtime", "numpy", "dotenv"]
)

# Shared cache for session messages
# Format: {session_id: [{"role": str, "content": str, "type": str}]}
_session_history = {}
_HISTORY_FILE = Path(__file__).parent / "history_cache.json"

def _load_history():
    """Load session history from JSON file if it exists."""
    global _session_history
    if _HISTORY_FILE.exists():
        try:
            with open(_HISTORY_FILE, 'r', encoding='utf-8') as f:
                _session_history = json.load(f)
        except Exception as e:
            print(f"Warning: Could not load history from {_HISTORY_FILE}: {e}", file=sys.stderr)

def _save_history():
    """Save session history to JSON file."""
    try:
        with open(_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(_session_history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: Could not save history to {_HISTORY_FILE}: {e}", file=sys.stderr)

# Load existing history on startup
_load_history()

def get_api() -> DeepSeekAPI:
    """Helper to load API client with token from environment."""
    token = os.getenv("DEEPSEEK_AUTH_TOKEN") or os.getenv("DEEPSEEK_API_KEY")
    if not token:
        raise ValueError(
            "DEEPSEEK_AUTH_TOKEN or DEEPSEEK_API_KEY environment variable is not set. "
            "Please configure it in your environment or .env file."
        )
    return DeepSeekAPI(token)

@mcp.tool()
def create_session() -> str:
    """
    Create a new DeepSeek chat session.
    
    Returns:
        The new session ID (UUID string).
    """
    try:
        api = get_api()
        session_id = api.create_chat_session()
        return session_id
    except Exception as e:
        return f"Error creating session: {e}"

@mcp.tool()
def get_sessions(count: int = 20) -> str:
    """
    Fetch a list of existing chat sessions (conversations) from the DeepSeek account.
    
    Args:
        count: Number of sessions to fetch (default: 20).
        
    Returns:
        JSON string listing the latest conversations.
    """
    try:
        api = get_api()
        sessions = api.get_chat_sessions(count=count)
        return json.dumps(sessions, indent=2)
    except Exception as e:
        return f"Error fetching sessions: {e}"

@mcp.tool()
def upload_image(image_path: str) -> str:
    """
    Upload an image file to DeepSeek's vision engine and wait for it to be ready.
    
    Args:
        image_path: Absolute path to the image file on your system (e.g., PNG, JPG).
        
    Returns:
        The uploaded file_id to pass to ask_deepseek, or an error message.
    """
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        return f"Error: Image file not found at path: {image_path}"
    
    try:
        api = get_api()
        file_id = api.upload_file(str(path))
        return file_id
    except Exception as e:
        return f"Error uploading image: {e}"

@mcp.tool()
def ask_deepseek(
    prompt: str,
    thinking: bool = True,
    search: bool = False,
    session_id: Optional[str] = None,
    file_ids: Optional[List[str]] = None
) -> str:
    """
    Ask DeepSeek a question. Exposes the free web chat model.
    
    Args:
        prompt: The question or instructions for the model.
        thinking: Enable thinking/reasoning mode (DeepSeek-R1). Defaults to True.
        search: Enable web search mode. Defaults to False.
        session_id: Optional session ID to continue a thread. If omitted, a new one is created.
        file_ids: Optional list of file/image IDs (obtained from upload_image) to attach.
    """
    try:
        api = get_api()
    except Exception as e:
        return str(e)

    # Use existing session or create a new one
    active_session_id = session_id
    if not active_session_id:
        try:
            active_session_id = api.create_chat_session()
        except Exception as e:
            return f"Error initializing new chat session: {e}"

    ref_files = file_ids or []
    
    result = {
        "thinking": "",
        "text": "",
        "sources": []
    }
    
    try:
        chunks = api.chat_completion(
            active_session_id,
            prompt,
            thinking_enabled=thinking,
            search_enabled=search,
            ref_file_ids=ref_files
        )
        
        for chunk in chunks:
            if chunk["type"] == "thinking":
                result["thinking"] += chunk["content"]
            elif chunk["type"] == "text":
                result["text"] += chunk["content"]
            elif chunk["type"] == "sources":
                result["sources"].extend(chunk.get("sources", []))
                
    except AuthenticationError:
        return "Authentication Error: Invalid or expired DEEPSEEK_AUTH_TOKEN."
    except RateLimitError:
        return "Rate Limit Error: DeepSeek is currently busy or rate-limiting requests. Please retry in a moment."
    except NetworkError as e:
        return f"Network Error: Unable to communicate with DeepSeek. Details: {e}"
    except APIError as e:
        return f"API Error: {e}"
    except Exception as e:
        return f"Unexpected Error: {e}"

    # Save to local history cache
    history = _session_history.setdefault(active_session_id, [])
    history.append({"role": "user", "content": prompt, "type": "text"})
    if result["thinking"]:
        history.append({"role": "assistant", "content": result["thinking"], "type": "thinking"})
    if result["text"]:
        history.append({"role": "assistant", "content": result["text"], "type": "text"})
    if result["sources"]:
        history.append({"role": "assistant", "content": json.dumps(result["sources"]), "type": "sources"})
    # Persist to disk
    _save_history()

    # Format output for the user/client
    output_parts = []
    
    # 1. Add session ID reference
    output_parts.append(f"Session ID: {active_session_id}\n")
    
    # 2. Add thinking output if present
    if result["thinking"]:
        output_parts.append("<thinking>")
        output_parts.append(result["thinking"].strip())
        output_parts.append("</thinking>\n")
        
    # 3. Add text response
    if result["text"]:
        output_parts.append(result["text"].strip())
    else:
        output_parts.append("(No text response was generated)")
        
    # 4. Add search sources if present
    if result["sources"]:
        output_parts.append("\n\nSources:")
        for idx, src in enumerate(result["sources"], 1):
            title = src.get("title") or "Untitled"
            url = src.get("url") or "No link"
            output_parts.append(f"[{idx}] {title} - {url}")
            
    return "\n".join(output_parts)

@mcp.resource("deepseek://conversations")
def list_conversations() -> str:
    """
    Get a list of all active conversation IDs cached locally, with details.
    """
    conversations_info = []
    for sid, messages in _session_history.items():
        # Find the last user message for display
        user_msgs = [m for m in messages if m["role"] == "user"]
        last_prompt = user_msgs[-1]["content"] if user_msgs else "New Conversation"
        # Count assistant responses
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        conversations_info.append({
            "session_id": sid,
            "last_prompt": last_prompt[:60] + ("..." if len(last_prompt) > 60 else ""),
            "message_count": len(messages),
            "user_messages": len(user_msgs),
            "assistant_messages": len(assistant_msgs),
            "last_message": messages[-1]["content"][:60] + ("..." if len(messages[-1]["content"]) > 60 else "") if messages else ""
        })
    return json.dumps(conversations_info, indent=2)

@mcp.resource("deepseek://conversations/{session_id}")
def get_conversation_history(session_id: str) -> str:
    """
    Get the detailed chat history of a specific conversation from the local cache.
    If not found, returns an error. For full history retrieval from DeepSeek's servers,
    consider using the `get_sessions` tool to fetch the list, but note that DeepSeek's API
    does not expose message contents through the session list endpoint.
    """
    if session_id not in _session_history:
        # Check if the session might exist but we don't have messages; give a helpful message
        return json.dumps({
            "error": f"Session {session_id} not found in local cache. This could be because:"
                     f" - No messages have been sent in this session via this server."
                     f" - The server was restarted and history was not persisted (now fixed with file storage)."
                     f" - The session ID is from DeepSeek's server but not used here yet."
                     f" To see all sessions from DeepSeek, use the `get_sessions` tool."
        }, indent=2)
    return json.dumps(_session_history[session_id], indent=2)

@mcp.prompt()
def code_helper(code: str) -> str:
    """
    Provide expert optimization and refactoring advice on the provided snippet.
    """
    return f"Analyze the following code and suggest performance enhancements, clean architecture refactoring, and potential bugs:\n\n```\n{code}\n```"

@mcp.prompt()
def debug_assistant(error_log: str) -> str:
    """
    Create a troubleshooting plan for a given traceback or error log.
    """
    return f"Troubleshoot the following error traceback or log and propose a step-by-step resolution:\n\n```\n{error_log}\n```"

if __name__ == "__main__":
    # Standard entry point to run FastMCP stdio server
    mcp.run()
