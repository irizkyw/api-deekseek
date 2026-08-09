import os
import sys
import time
import json
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

# Add workspace root to path so we can import deepseek_api
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from deepseek_api import DeepSeekAPI

load_dotenv()

app = FastAPI(title="DeepSeek Web Chat to OpenAI API Bridge")

# Retrieve the token
token = os.getenv("DEEPSEEK_AUTH_TOKEN")
if not token:
    print("WARNING: DEEPSEEK_AUTH_TOKEN not found in .env file!")
    # Fallback to check if user passed it in command environment
    token = os.getenv("DEEPSEEK_API_KEY")

try:
    api = DeepSeekAPI(token)
except Exception as e:
    print(f"Error initializing DeepSeekAPI: {e}")
    api = None

class Message(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: Optional[bool] = False
    temperature: Optional[float] = 1.0

def build_prompt(messages: List[Message]) -> str:
    prompt_parts = []
    for msg in messages:
        if msg.role == "system":
            prompt_parts.append(f"System: {msg.content}")
        elif msg.role == "user":
            prompt_parts.append(f"User: {msg.content}")
        elif msg.role == "assistant":
            prompt_parts.append(f"Assistant: {msg.content}")
    return "\n\n".join(prompt_parts)

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    if api is None:
        raise HTTPException(status_code=500, detail="DeepSeekAPI is not initialized. Check your DEEPSEEK_AUTH_TOKEN.")

    prompt = build_prompt(request.messages)
    chat_id = f"chatcmpl-{int(time.time())}"
    
    try:
        session_id = api.create_chat_session()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create chat session: {str(e)}")

    if request.stream:
        async def event_generator():
            try:
                # Get the generator from deepseek4free
                chunks = api.chat_completion(
                    session_id,
                    prompt,
                    thinking_enabled=False, # Disable thinking for cleaner JSON output parsing by Graphify
                    search_enabled=False
                )
                
                for chunk in chunks:
                    # We only yield content of type 'text'
                    if chunk.get('type') == 'text':
                        content = chunk.get('content', '')
                        if content:
                            chunk_data = {
                                "id": chat_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": request.model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": content},
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(chunk_data)}\n\n"
                
                # Yield the final stop chunk
                stop_data = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": request.model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }]
                }
                yield f"data: {json.dumps(stop_data)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_data = {"error": {"message": str(e), "type": "api_error"}}
                yield f"data: {json.dumps(err_data)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    
    else:
        # Non-streaming mode
        try:
            chunks = api.chat_completion(
                session_id,
                prompt,
                thinking_enabled=False,
                search_enabled=False
            )
            full_text = ""
            for chunk in chunks:
                if chunk.get('type') == 'text':
                    full_text += chunk.get('content', '')
            
            response_data = {
                "id": chat_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_text
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": len(prompt) // 4, # Rough estimate
                    "completion_tokens": len(full_text) // 4,
                    "total_tokens": (len(prompt) + len(full_text)) // 4
                }
            }
            return response_data
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    print("Starting OpenAI Bridge on http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
