# DeepSeek4Free

A Python package for interacting with the DeepSeek AI chat API. This package provides a clean interface to interact with DeepSeek's chat model, with support for streaming responses, thinking process visibility, and web search capabilities.

### Learn how to reverse engineer private api's !!
- and reverse wasm like it was required here
- [whop.com/reverser-academy](https://whop.com/reverser-academy/) (beta)


> ⚠️ **Service Notice**: DeepSeek API is currently experiencing high load. Work is in progress to integrate additional API providers. Please expect intermittent errors.

> 📝 **Note**: If you encounter any errors, please ensure you are using the latest version of this library. The DeepSeek API may change frequently, and updates are released to maintain compatibility.

## ✨ Features

- 🔄 **Streaming Responses**: Real-time interaction with token-by-token output
- 🤔 **Thinking Process**: Optional visibility into the model's reasoning steps
- 🔍 **Web Search**: Optional integration for up-to-date information
- 💬 **Session Management**: Persistent chat sessions with conversation history
- ⚡ **Efficient PoW**: WebAssembly-based proof of work implementation
- 🛡️ **Error Handling**: Comprehensive error handling with specific exceptions
- ⏱️ **No Timeouts**: Designed for long-running conversations without timeouts
- 🧵 **Thread Support**: Parent message tracking for threaded conversations

## 📦 Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/deepseek4free.git
cd deepseek4free
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## 🔑 Authentication

To use this package, you need a DeepSeek auth token. Here's how to obtain it:

If you know how to use chrome devtools, simply run this snipped in the console:

```js
JSON.parse(localStorage.getItem("userToken")).value
```

### Method 1: From LocalStorage (Recommended)

<img width="1150" alt="image" src="https://github.com/user-attachments/assets/b4e11650-3d1b-4638-956a-c67889a9f37e" />

1. Visit [chat.deepseek.com](https://chat.deepseek.com)
2. Log in to your account
3. Open browser developer tools (F12 or right-click > Inspect)
4. Go to Application tab (if not visible, click >> to see more tabs)
5. In the left sidebar, expand "Local Storage"
6. Click on "https://chat.deepseek.com"
7. Find the key named `userToken`
8. Copy `"value"` - this is your authentication token

### Method 2: From Network Tab

Alternatively, you can get the token from network requests:

1. Visit [chat.deepseek.com](https://chat.deepseek.com)
2. Log in to your account
3. Open browser developer tools (F12)
4. Go to Network tab
5. Make any request in the chat
6. Find the request headers
7. Copy the `authorization` token (without 'Bearer ' prefix)

### Handling Cloudflare Challenges

If you encounter Cloudflare challenges ("Just a moment..." page), you'll need to get a `cf_clearance` cookie. Run this command:

```bash
python -m dsk.bypass
```

This will:
1. Open an undetected browser
2. Visit DeepSeek and solve the Cloudflare challenge
3. Capture and save the `cf_clearance` cookie
4. The cookie will be automatically used in future requests

You only need to run this when:
- You get Cloudflare challenges in your requests
- Your existing cf_clearance cookie expires
- You see the error "Please wait a few minutes before trying again"

The captured cookie will be stored in `dsk/cookies.json` and automatically used by the API.

## 📚 Usage

### Basic Example

```python
from dsk.api import DeepSeekAPI

# Initialize with your auth token
api = DeepSeekAPI("YOUR_AUTH_TOKEN")

# Create a new chat session
chat_id = api.create_chat_session()

# Simple chat completion
prompt = "What is Python?"
for chunk in api.chat_completion(chat_id, prompt):
    if chunk['type'] == 'text':
        print(chunk['content'], end='', flush=True)
```

### Advanced Features

#### Thinking Process Visibility

The thinking process shows the model's reasoning steps:

```python
# With thinking process enabled
for chunk in api.chat_completion(
    chat_id,
    "Explain quantum computing",
    thinking_enabled=True
):
    if chunk['type'] == 'thinking':
        print(f"🤔 Thinking: {chunk['content']}")
    elif chunk['type'] == 'text':
        print(chunk['content'], end='', flush=True)
```

#### Web Search Integration

Enable web search for up-to-date information:

```python
# With web search enabled
for chunk in api.chat_completion(
    chat_id,
    "What are the latest developments in AI?",
    thinking_enabled=True,
    search_enabled=True
):
    if chunk['type'] == 'thinking':
        print(f"🔍 Searching: {chunk['content']}")
    elif chunk['type'] == 'text':
        print(chunk['content'], end='', flush=True)
```

#### Threaded Conversations

Create threaded conversations by tracking parent messages:

```python
# Start a conversation
chat_id = api.create_chat_session()

# Send initial message
parent_id = None
for chunk in api.chat_completion(chat_id, "Tell me about neural networks"):
    if chunk['type'] == 'text':
        print(chunk['content'], end='', flush=True)
    elif 'message_id' in chunk:
        parent_id = chunk['message_id']

# Send follow-up question in the thread
for chunk in api.chat_completion(
    chat_id,
    "How do they compare to other ML models?",
    parent_message_id=parent_id
):
    if chunk['type'] == 'text':
        print(chunk['content'], end='', flush=True)
```

### Error Handling

The package provides specific exceptions for different error scenarios:

```python
from dsk.api import (
    DeepSeekAPI, 
    AuthenticationError,
    RateLimitError,
    NetworkError,
    CloudflareError,
    APIError
)

try:
    api = DeepSeekAPI("YOUR_AUTH_TOKEN")
    chat_id = api.create_chat_session()
    
    for chunk in api.chat_completion(chat_id, "Your prompt here"):
        if chunk['type'] == 'text':
            print(chunk['content'], end='', flush=True)
            
except AuthenticationError:
    print("Authentication failed. Please check your token.")
except RateLimitError:
    print("Rate limit exceeded. Please wait before making more requests.")
except CloudflareError as e:
    print(f"Cloudflare protection encountered: {str(e)}")
except NetworkError:
    print("Network error occurred. Check your internet connection.")
except APIError as e:
    print(f"API error occurred: {str(e)}")


## 🤖 Model Context Protocol (MCP) Server

`deepseek4free` now includes a Model Context Protocol (MCP) server so you can connect this free DeepSeek web client (supporting R1 thinking mode, web search, and image vision) directly to host tools like Claude Desktop, Cursor, or Cline.

### Configuration (e.g. Claude Desktop)

Add the following configuration to your `claude_desktop_config.json`:

**Windows (`%APPDATA%/Claude/claude_desktop_config.json`):**
```json
{
  "mcpServers": {
    "deepseek-free": {
      "command": "python",
      "args": [
        "d:/projs/deepseek/deepseek4free/mcp_server.py"
      ],
      "env": {
        "DEEPSEEK_AUTH_TOKEN": "YOUR_DEEPSEEK_AUTH_TOKEN"
      }
    }
  }
}
```

Make sure to replace `YOUR_DEEPSEEK_AUTH_TOKEN` with your actual authentication token (or keep it in the `.env` file of this repository, which the server loads automatically).

### Exposed Tools, Resources, and Prompts

Once connected, your agent can access:
- **Tools**:
  - `ask_deepseek`: Sends prompts with optional thinking, web search, and attached image file IDs.
  - `upload_image`: Uploads an image file from disk and returns a `file_id` which can be passed to `ask_deepseek`.
  - `create_session`: Creates a new session ID.
  - `get_sessions`: Fetches your latest chat sessions from the DeepSeek web app.
- **Resources**:
  - `deepseek://conversations`: Lists locally cached active conversation sessions.
  - `deepseek://conversations/{session_id}`: Views history details for a specific session.
- **Prompts**:
  - `code_helper`: Helper to review, analyze, and optimize a block of code.
  - `debug_assistant`: Helper to create a troubleshooting plan for tracebacks or logs.

