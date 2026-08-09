# Graph Report - D:\projs\deepseek\deepseek4free  (2026-06-30)

## Corpus Check
- Corpus is ~5,919 words - fits in a single context window. You may not need a graph.

## Summary
- 82 nodes · 153 edges · 12 communities (9 shown, 3 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 12 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 11|Community 11]]

## God Nodes (most connected - your core abstractions)
1. `DeepSeekAPI` - 16 edges
2. `DeepSeekPOW` - 12 edges
3. `CloudflareBypasser` - 11 edges
4. `APIError` - 10 edges
5. `DeepSeekError` - 9 edges
6. `AuthenticationError` - 8 edges
7. `RateLimitError` - 7 edges
8. `NetworkError` - 7 edges
9. `bypass_cloudflare()` - 7 edges
10. `DeepSeekHash` - 5 edges

## Surprising Connections (you probably didn't know these)
- `ChatCompletionRequest` --uses--> `DeepSeekAPI`  [INFERRED]
  openai_bridge.py → dsk/api.py
- `Message` --uses--> `DeepSeekAPI`  [INFERRED]
  openai_bridge.py → dsk/api.py
- `bypass_cloudflare()` --calls--> `CloudflareBypasser`  [INFERRED]
  dsk/server.py → dsk/CloudflareBypasser.py
- `CookieResponse` --uses--> `CloudflareBypasser`  [INFERRED]
  dsk/server.py → dsk/CloudflareBypasser.py
- `NetworkError` --uses--> `DeepSeekPOW`  [INFERRED]
  dsk/api.py → dsk/pow.py

## Import Cycles
- None detected.

## Communities (12 total, 3 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.24
Nodes (10): AuthenticationError, CloudflareError, DeepSeekError, RateLimitError, Base exception for all DeepSeek API errors, Raised when authentication fails, Raised when API rate limit is exceeded, Raised when Cloudflare blocks the request (+2 more)

### Community 1 - "Community 1"
Cohesion: 0.27
Nodes (9): bypass_cloudflare(), CookieResponse, get_cookies(), get_html(), is_safe_url(), ChromiumPage, Verify if the page has loaded properly, verify_page_loaded() (+1 more)

### Community 3 - "Community 3"
Cohesion: 0.39
Nodes (7): DeepSeekAPI, main(), print_response(), Any, Run a chat example with error handling, Helper function to print response chunks in real-time, run_chat_example()

### Community 4 - "Community 4"
Cohesion: 0.29
Nodes (3): DeepSeekHash, Any, Solves a proof-of-work challenge and returns the encoded response

### Community 5 - "Community 5"
Cohesion: 0.60
Nodes (5): BaseModel, build_prompt(), chat_completions(), ChatCompletionRequest, Message

### Community 6 - "Community 6"
Cohesion: 0.47
Nodes (3): APIError, Creates a new chat session and returns the session ID, Raised when API returns an error response

### Community 7 - "Community 7"
Cohesion: 0.40
Nodes (3): NetworkError, Send a message and get streaming response          Args:             chat_ses, Raised when network communication fails

### Community 8 - "Community 8"
Cohesion: 0.50
Nodes (3): get_and_save_cookies(), Validate that cf_clearance cookie is present and not empty, validate_cookies()

## Knowledge Gaps
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeepSeekError` connect `Community 0` to `Community 1`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.245) - this node is a cross-community bridge._
- **Why does `bypass_cloudflare()` connect `Community 1` to `Community 2`?**
  _High betweenness centrality (0.229) - this node is a cross-community bridge._
- **Why does `DeepSeekAPI` connect `Community 3` to `Community 0`, `Community 5`, `Community 6`, `Community 7`, `Community 9`, `Community 11`?**
  _High betweenness centrality (0.227) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `DeepSeekAPI` (e.g. with `DeepSeekPOW` and `ChatCompletionRequest`) actually correct?**
  _`DeepSeekAPI` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `DeepSeekPOW` (e.g. with `APIError` and `AuthenticationError`) actually correct?**
  _`DeepSeekPOW` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `CloudflareBypasser` (e.g. with `bypass_cloudflare()` and `CookieResponse`) actually correct?**
  _`CloudflareBypasser` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Base exception for all DeepSeek API errors`, `Raised when authentication fails`, `Raised when API rate limit is exceeded` to the rest of the system?**
  _16 weakly-connected nodes found - possible documentation gaps or missing edges._