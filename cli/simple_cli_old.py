import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dsk.api import DeepSeekAPI, AuthenticationError, RateLimitError, NetworkError, APIError
from typing import Generator, Dict, Any
from dotenv import load_dotenv

load_dotenv()

def print_response(chunks: Generator[Dict[str, Any], None, None]) -> None:
    """Helper function to print response chunks in real-time"""
    print_thinking_header = True
    print_response_header = True

    try:
        for chunk in chunks:
            if chunk['type'] == 'thinking':
                if print_thinking_header:
                    print("\n🤔 Thinking: ", end="", flush=True)
                    print_thinking_header = False
                print(chunk['content'], end="", flush=True)
            elif chunk['type'] == 'text':
                if print_response_header:
                    if not print_thinking_header:
                        print() # Newline after thinking
                    print("\n💬 Response: ", end="", flush=True)
                    print_response_header = False
                print(chunk['content'], end="", flush=True)
        print()
    except KeyError as e:
        print(f"\n❌ Error: Malformed response chunk - missing key {str(e)}")

def run_chat_example(api: DeepSeekAPI, title: str, prompt: str, thinking_enabled: bool = True, search_enabled: bool = False) -> None:
    """Run a chat example with error handling"""
    print(f"\n{title}")
    print("-" * 80)

    try:
        chunks = api.chat_completion(
            api.create_chat_session(),
            prompt,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled
        )
        print_response(chunks)

    except AuthenticationError as e:
        print(f"❌ Authentication Error: {str(e)}")
        print("Please check your authentication token and try again.")
        sys.exit(1)
    except RateLimitError as e:
        print(f"❌ Rate Limit Error: {str(e)}")
        print("Please wait a moment before making more requests.")
    except NetworkError as e:
        print(f"❌ Network Error: {str(e)}")
        print("Please check your internet connection and try again.")
    except APIError as e:
        print(f"❌ API Error: {str(e)}")
        if e.status_code:
            print(f"Status code: {e.status_code}")
    except Exception as e:
        print(f"❌ Unexpected Error: {str(e)}")
        print("Please report this issue if it persists.")

def main():
    try:
        api = DeepSeekAPI(os.getenv("DEEPSEEK_AUTH_TOKEN"))

        thinking_enabled = True
        search_enabled = False

        print("=== DeepSeek4Free Interactive CLI ===")
        print("Commands:")
        print("  /thinking - Toggle thinking mode")
        print("  /search   - Toggle web search mode")
        print("  /exit     - Exit the program")
        print("=====================================")

        while True:
            status = f"[Thinking: {'ON' if thinking_enabled else 'OFF'} | Search: {'ON' if search_enabled else 'OFF'}]"
            try:
                prompt = input(f"\n{status}\nQuery > ").strip()
            except EOFError:
                break

            if not prompt:
                continue

            if prompt.lower() == '/exit':
                break
            elif prompt.lower() == '/thinking':
                thinking_enabled = not thinking_enabled
                print(f"Thinking mode set to: {'ON' if thinking_enabled else 'OFF'}")
                continue
            elif prompt.lower() == '/search':
                search_enabled = not search_enabled
                print(f"Web search mode set to: {'ON' if search_enabled else 'OFF'}")
                continue

            run_chat_example(
                api,
                f"Query: {prompt}",
                prompt,
                thinking_enabled=thinking_enabled,
                search_enabled=search_enabled
            )

    except KeyboardInterrupt:
        print("\n\n⚠️ Operation cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()