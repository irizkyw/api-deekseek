"""
Quick debug: upload image then send chat with it, dump ALL raw SSE chunks.
Run: python test_image_chat.py
"""
import os, sys, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from dsk.api import DeepSeekAPI

TOKEN = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AUTH_TOKEN") or ""
if not TOKEN:
    # try to read from .env directly
    for line in Path(".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            if "key" in k.lower() or "token" in k.lower() or "auth" in k.lower():
                TOKEN = v.strip().strip('"').strip("'")
                print(f"Using token from .env key: {k}")
                break

if not TOKEN:
    print("ERROR: No token found. Set DEEPSEEK_API_KEY in .env")
    sys.exit(1)

api = DeepSeekAPI(TOKEN)

# 1. create session
print("Creating session...")
session_id = api.create_chat_session()
print(f"Session: {session_id}")

# 2. upload test image (use temp_clipboard.png if exists)
img_path = "temp_clipboard.png"
if not Path(img_path).exists():
    print(f"No {img_path} found, skipping image test")
    file_id = None
else:
    print(f"Uploading {img_path}...")
    file_id = api.upload_file(img_path)
    print(f"File ID: {file_id}")
    
    # Also call fetch_files like browser does
    print("Fetching file metadata...")
    meta = api.fetch_files([file_id])
    print(f"Fetch response: {json.dumps(meta, indent=2)}")

# 3. send message — patch chat_completion to dump raw chunks
from curl_cffi import requests as curl_requests
import json as _json

def raw_stream_test(api, session_id, prompt, ref_file_ids):
    from dsk.pow import DeepSeekPOW
    
    json_data = {
        'chat_session_id': session_id,
        'parent_message_id': None,
        'prompt': prompt,
        'ref_file_ids': ref_file_ids or [],
        'thinking_enabled': False,
        'search_enabled': False,
    }
    print(f"\n=== REQUEST BODY ===\n{_json.dumps(json_data, indent=2)}\n")
    
    challenge = api._get_pow_challenge()
    pow_resp = api.pow_solver.solve_challenge(challenge)
    headers = api._get_headers(pow_resp)
    
    response = curl_requests.post(
        f"{api.BASE_URL}/chat/completion",
        headers=headers,
        json=json_data,
        cookies=api.cookies,
        impersonate='chrome120',
        stream=True,
        timeout=None
    )
    print(f"Response status: {response.status_code}")
    print("\n=== RAW STREAM CHUNKS ===")
    
    count = 0
    for chunk in response.iter_lines():
        if chunk:
            decoded = chunk.decode('utf-8', 'ignore')
            print(repr(decoded))
            count += 1
            if count > 100:
                print("... (truncated at 100 chunks)")
                break
    print(f"\nTotal chunks: {count}")

raw_stream_test(
    api, session_id,
    prompt="gambar apa ini?",
    ref_file_ids=[file_id] if file_id else []
)
