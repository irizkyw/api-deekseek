import sys; sys.path.insert(0, '.')
from dsk.api import DeepSeekAPI
from datetime import datetime, timezone

token = open('.env').read().split('=',1)[1].strip().strip('"').strip("'")
api = DeepSeekAPI(token)

sid = '69379390-4585-4be8-8bd9-fd8b67c25372'
print(f'Fetching: {sid}')
msgs = api.get_chat_history(sid)
print(f'Messages: {len(msgs)}')

for msg in msgs:
    role = (msg.get('role') or '').lower()
    inserted_at = msg.get('inserted_at', 0)
    ts = datetime.fromtimestamp(float(inserted_at), tz=timezone.utc).strftime('%Y-%m-%d %H:%M') if inserted_at else ''
    content = msg.get('content', '') or ''
    thinking = msg.get('thinking_content', '') or ''
    elapsed = msg.get('thinking_elapsed_secs')

    print(f'\n[{role.upper()}] {ts}')
    if role == 'user':
        # Strip system instructions
        for marker in ['\n\n=== SYSTEM INSTRUCTION', '\n\n=== SYSTEM INSTRUCTIONS']:
            idx = content.find(marker)
            if idx != -1:
                content = content[:idx]
        print(f'  Content: {content.strip()[:200]!r}')
    elif role == 'assistant':
        if thinking:
            print(f'  Thinking ({elapsed}s): {thinking[:100]!r}')
        print(f'  Response: {content[:200]!r}')
