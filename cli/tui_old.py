"""
DeepSeek Interactive TUI — Codex/Gemini CLI style, built with Textual.

Run:
    pip install textual rich-pixels Pillow pyperclip --break-system-packages
    python main_cli.py

Drop this file next to your existing dsk/ package (same import path as cli.py).

Image paste:
    Ctrl+V (or /paste, /v) grabs whatever is on the system clipboard — an
    image, copied file paths, or text — and shows an inline ANSI/half-block
    thumbnail preview in the chat log before uploading, similar to pasting
    an image into Claude or Gemini CLI.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import re
import traceback
import json
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

try:
    import importlib.util
    _client_path = Path(__file__).resolve().parent.parent / "mcp" / "client.py"
    if _client_path.exists():
        _spec = importlib.util.spec_from_file_location("local_mcp_client", _client_path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        MCPManager = _mod.MCPManager
    else:
        from mcp_client import MCPManager
except Exception:
    try:
        from mcp_client import MCPManager
    except ImportError:
        MCPManager = None

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Header, Footer, Static, Input, RichLog, Button
from textual.reactive import reactive
from textual.worker import Worker, get_current_worker
from textual import work, events
from textual.binding import Binding

from rich.markdown import Markdown
from rich.text import Text
from rich.panel import Panel

# Fallback Math renderer for LaTeX expressions
class Math:
    def __init__(self, content: str, style: str = ""):
        self.content = content
        self.style = style

    def __rich__(self):
        # Render the math content with a nice border and italic style
        return Panel(
            Text(self.content, style="italic cyan"),
            title="[bold cyan]Equation[/bold cyan]",
            border_style="cyan",
            expand=False,
            padding=(0, 2)
        )

try:
    from rich_pixels import Pixels
except ImportError:
    Pixels = None

try:
    from PIL import Image, ImageGrab
except ImportError:
    Image = None
    ImageGrab = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from dsk.api import DeepSeekAPI, AuthenticationError, RateLimitError, NetworkError, APIError

load_dotenv()

PREVIEW_MAX_WIDTH = 36   # chars wide for the chat-log thumbnail
CHIP_MAX_WIDTH = 14       # chars wide for the small compose-area chip

def strip_comments_safely(text: str) -> str:
    """Safely strip // and /* */ comments while preserving URLs with http:// or https://."""
    def replacer(match):
        if match.group(1) is not None:
            return match.group(1)
        return ""
    pattern = r'("(?:\\.|[^"\\])*")|//.*?$|/\*.*?\*/'
    return re.sub(pattern, replacer, text, flags=re.DOTALL | re.MULTILINE)

def clean_json_str(s: str) -> str:
    """Cleans JSON strings from comments and trailing commas before closing braces."""
    s = strip_comments_safely(s)
    while True:
        sub = re.sub(r",\s*([\}\]])", r"\1", s)
        if sub == s:
            break
        s = sub
    return s.strip()

ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])|\x1b\[[0-9;]*[mGKHFABCDEJsuhl]')

def strip_ansi(text: str) -> str:
    """Remove ANSI/VT100 escape codes from text."""
    return ANSI_ESCAPE.sub('', text)

def detect_repetition(text: str, window: int = 1500, min_repeats: int = 4) -> bool:
    """Detects if recent generated text has entered a degenerate repetition loop."""
    if len(text) < 400:
        return False
    tail = text[-window:] if len(text) > window else text
    for cycle in (20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 150, 200):
        if len(tail) < cycle * min_repeats:
            continue
        sample = tail[-cycle:]
        if tail.count(sample) >= min_repeats:
            return True
    return False

def sanitize_for_display(text: str) -> str:
    """Sanitizes text for clean terminal display, collapsing repetitive token loops and huge tool call arguments."""
    if not text:
        return text

    # 1. Collapse repeating escaped patterns (like \ntwilio\nvonage...)
    text = re.sub(r"((?:\\[nr][a-zA-Z0-9_\.\-/]+){2,10}?)\1{3,}", r"\1\n[dim]... (repetitive pattern collapsed) ...[/dim]", text)

    # 2. Collapse repeating multi-line patterns
    text = re.sub(r"((?:[\r\n]+[^\r\n]{1,80}){2,10}?)\1{3,}", r"\1\n[dim]... (repetitive pattern collapsed) ...[/dim]", text)

    # 3. Truncate overly long tool call code blocks in markdown preview
    def _truncate_args(match):
        raw_json = match.group(1)
        try:
            data = json.loads(raw_json)
            if isinstance(data, dict) and "tool" in data:
                args = data.get("arguments", {})
                if isinstance(args, dict):
                    clean_args = {}
                    modified = False
                    for k, v in args.items():
                        if isinstance(v, str) and len(v) > 250:
                            v_clean = v[:250].replace("\n", " ").replace("\\n", " ")
                            clean_args[k] = f"{v_clean} ... [+{len(v)-250} chars hidden in preview]"
                            modified = True
                        else:
                            clean_args[k] = v
                    if modified:
                        clean_data = {"tool": data["tool"], "arguments": clean_args}
                        clean_json = json.dumps(clean_data, indent=2, ensure_ascii=False)
                        return f"```json\n{clean_json}\n```"
        except Exception:
            pass
        return match.group(0)

    text = re.sub(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", _truncate_args, text)
    return text

def format_tool_output(raw: str, max_lines: int = 150) -> str:
    """
    Clean and format tool output for console-style display:
    - Strip ANSI escape codes
    - Unescape literal \\n and \\r\\n into real line breaks
    - Collapse excessive blank lines and repetitive patterns
    - Truncate to max_lines cleanly
    """
    text = strip_ansi(raw)

    # If text has escaped newlines like '\n' as literal string, unescape them so they split properly!
    if '\\n' in text:
        text = text.replace('\\r\\n', '\n').replace('\\n', '\n')

    # Collapse repetitive lines
    text = re.sub(r"((?:[\r\n]+[^\r\n]{1,80}){2,10}?)\1{3,}", r"\1\n[dim]... (repetitive lines collapsed) ...[/dim]", text)

    # Split on carriage returns (\r) — keep only last segment of each \r-overwritten line
    raw_lines = []
    for line in text.split('\n'):
        if '\r' in line:
            line = line.split('\r')[-1]
        raw_lines.append(line)

    clean_lines = []
    prev_line = None
    rep_count = 0
    for line in raw_lines:
        stripped = line.rstrip()
        # Collapse excessive consecutive blank lines
        if stripped == '' and clean_lines and clean_lines[-1] == '':
            continue
        # Collapse repetitive duplicate lines
        if stripped == prev_line and stripped != '':
            rep_count += 1
            if rep_count <= 2:
                clean_lines.append(stripped)
            elif rep_count == 3:
                clean_lines.append("[dim]... (duplicate line omitted) ...[/dim]")
            continue
        else:
            prev_line = stripped
            rep_count = 1

        clean_lines.append(stripped)

    # Trim leading/trailing blank lines
    while clean_lines and clean_lines[0] == '':
        clean_lines.pop(0)
    while clean_lines and clean_lines[-1] == '':
        clean_lines.pop()

    total = len(clean_lines)
    if total > max_lines:
        half = max_lines // 2
        skipped = total - max_lines
        clean_lines = clean_lines[:half] + [f"[dim]... ({skipped} lines truncated for display) ...[/dim]"] + clean_lines[-half:]

    return '\n'.join(clean_lines)

def save_local_tool_log(target_hint: str, tool_name: str, args: dict, result_text: str) -> str:
    """Save tool output and scan logs locally to the user's laptop under reports/<target>/scans/."""
    try:
        raw_target = ""
        if isinstance(args, dict):
            raw_target = args.get("target") or args.get("url") or args.get("domain") or args.get("host") or ""
        if not raw_target and target_hint:
            raw_target = target_hint
        
        # Clean target: remove protocol, path, and port
        clean_target = re.sub(r"^https?://", "", str(raw_target)).split("/")[0].replace(":", "_").strip()
        clean_target = re.sub(r"[^a-zA-Z0-9_.-]", "_", clean_target)
        if not clean_target:
            clean_target = "general"

        out_dir = Path("reports") / clean_target / "scans"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        is_json = False
        parsed = None
        try:
            parsed = json.loads(result_text)
            is_json = True
        except Exception:
            pass

        ext = "json" if is_json else "txt"
        clean_tool = re.sub(r"[^a-zA-Z0-9_-]", "_", tool_name)
        file_path = out_dir / f"{ts}_{clean_tool}.{ext}"

        if is_json and parsed is not None:
            file_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            file_path.write_text(result_text, encoding="utf-8")

        # Append to scans_summary.md
        summary_file = Path("reports") / clean_target / "scans_summary.md"
        if not summary_file.exists():
            summary_file.write_text(
                f"# Scan Summary for {clean_target}\n\n| Timestamp | Tool | Arguments | Log File |\n| --- | --- | --- | --- |\n",
                encoding="utf-8"
            )

        args_summary = json.dumps(args, ensure_ascii=False)[:60].replace("|", "\\|") if isinstance(args, dict) else ""
        rel_path = file_path.relative_to(Path("reports") / clean_target)
        with summary_file.open("a", encoding="utf-8") as sf:
            sf.write(f"| {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | `{tool_name}` | `{args_summary}` | [{file_path.name}]({rel_path}) |\n")

        return str(file_path)
    except Exception:
        return ""

def save_local_report(target_hint: str, report_text: str, session_id: str = "") -> str:
    """Save assessment report directly to reports/<target>/ on user's laptop."""
    try:
        clean_target = re.sub(r"^https?://", "", str(target_hint or "general")).split("/")[0].replace(":", "_").strip()
        clean_target = re.sub(r"[^a-zA-Z0-9_.-]", "_", clean_target)
        if not clean_target:
            clean_target = "general"

        out_dir = Path("reports") / clean_target
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = out_dir / f"assessment_report_{ts}.md"

        content = f"# Security Assessment Report - {clean_target}\n\n"
        content += f"- **Target:** `{clean_target}`\n"
        content += f"- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        if session_id:
            content += f"- **Session ID:** `{session_id}`\n"
        content += "\n---\n\n"
        content += report_text.strip() + "\n"

        report_file.write_text(content, encoding="utf-8")
        return str(report_file)
    except Exception:
        return ""

def extract_tool_call(text: str):
    """Robustly extracts tool name and arguments from text, supporting diverse code block formats and raw JSON."""
    if not text:
        return None

    # Try fenced code blocks (``` or ```` with optional json tag)
    matches = re.findall(r"`{3,}(?:json)?\s*\n?(.*?)\n?`{3,}", text, re.DOTALL | re.IGNORECASE)
    for raw in matches:
        cleaned = clean_json_str(raw)
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict) and "tool" in data:
                return data.get("tool"), data.get("arguments", {})
        except Exception:
            pass

    # Fallback: scan for any balanced JSON block containing "tool"
    for m in re.finditer(r'"tool"\s*:', text):
        idx = m.start()
        start = text.rfind("{", 0, idx)
        if start != -1:
            depth = 0
            in_string = False
            escape = False
            for i in range(start, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == "\\":
                    escape = True
                    continue
                if c == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = text[start:i+1]
                            cleaned = clean_json_str(candidate)
                            try:
                                data = json.loads(cleaned)
                                if isinstance(data, dict) and "tool" in data:
                                    return data.get("tool"), data.get("arguments", {})
                            except Exception:
                                pass
                            break

    return None


# ----------------------------------------------------------------------
# Math rendering helper using rich.math
# ----------------------------------------------------------------------
def render_latex_in_text(text: str) -> list:
    """
    Parse LaTeX expressions in the text and return a list of Rich renderables.
    - Inline math \\( ... \\) is kept inline inside a Text block styled as italic cyan (NO box).
    - Display math $$ ... $$ and \\[ ... \\] are yielded as separate Math (Panel) blocks.
    - Bold text **...** is rendered with style "bold white".
    """
    result = []
    current_text = Text()
    i = 0
    n = len(text)
    
    def append_text_with_bold(plain_text: str):
        parts = plain_text.split('**')
        for idx, part in enumerate(parts):
            if idx % 2 == 1:
                current_text.append(part, style="bold white")
            else:
                current_text.append(part, style="#c9d1d9")

    while i < n:
        # Check for display math: $$
        if text.startswith('$$', i):
            end = text.find('$$', i + 2)
            if end != -1:
                math_content = text[i+2:end].strip()
                if len(current_text) > 0:
                    result.append(current_text)
                    current_text = Text()
                result.append(Math(math_content, style="math"))
                i = end + 2
                continue
                
        # Check for \[
        if text.startswith('\\[', i):
            end = text.find('\\]', i + 2)
            if end != -1:
                math_content = text[i+2:end].strip()
                if len(current_text) > 0:
                    result.append(current_text)
                    current_text = Text()
                result.append(Math(math_content, style="math"))
                i = end + 2
                continue
                
        # Check for \(
        if text.startswith('\\(', i):
            end = text.find('\\)', i + 2)
            if end != -1:
                math_content = text[i+2:end].strip()
                current_text.append(math_content, style="italic cyan")
                i = end + 2
                continue
                
        # Find next delimiter
        next_delim = n
        for delim in ('$$', '\\[', '\\('):
            pos = text.find(delim, i)
            if pos != -1 and pos < next_delim:
                next_delim = pos
                
        # Append plain text up to next delimiter
        plain_part = text[i:next_delim]
        append_text_with_bold(plain_part)
        i = next_delim
        
    if len(current_text) > 0:
        result.append(current_text)
        
    return result

# ----------------------------------------------------------------------
# Image preview helper
# ----------------------------------------------------------------------
def render_image_preview(path: str, max_width: int = PREVIEW_MAX_WIDTH):
    """Return a Rich-renderable thumbnail (half-block ANSI art)."""
    if Pixels is None or Image is None:
        return Text(f"[image: {Path(path).name}]", style="dim")
    try:
        img = Image.open(path)
        img = img.convert("RGB")
        w, h = img.size
        target_w = min(max_width, w)
        target_h = max(1, int(h * (target_w / w) * 0.5))  # *0.5 offsets char-cell aspect ratio
        img = img.resize((target_w, target_h))
        return Pixels.from_image(img)
    except Exception as e:
        return Text(f"[preview failed: {e}]", style="red")


def resolve_tagged_files(prompt: str) -> tuple[str, list[str]]:
    # Regex to find @followed by path, handles quotes and brackets: @[path], @"file name.txt", or @file.txt
    pattern = r'@(?:"([^"]+)"|\[([^\]]+)\]|([^\s]+))'
    matches = re.findall(pattern, prompt)
    
    file_paths = []
    for m in matches:
        path_str = m[0] or m[1] or m[2]
        path_str = path_str.strip('[]"\'').strip()
        if path_str:
            file_paths.append(path_str)

    # Auto-detect skills mentioned by name from .agents/skills/ (e.g. "report-executive", "recon")
    skills_dir = Path(".agents/skills")
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_file in skills_dir.glob("*.md"):
            skill_name = skill_file.stem.lower()
            # If skill name appears as a word in user prompt
            if re.search(rf'\b{re.escape(skill_name)}\b', prompt, re.IGNORECASE):
                if str(skill_file) not in file_paths and skill_file.name not in file_paths:
                    file_paths.append(str(skill_file))
        
    resolved_files_content = []
    clean_prompt = prompt
    
    for path_str in file_paths:
        p = Path(path_str)
        if not p.exists() and not p.is_absolute():
            # Try searching in .agents/skills/ or current directory
            candidates = [
                Path(".agents/skills") / p.name,
                Path(".agents/skills") / f"{p.name}.md",
                Path(p.name),
            ]
            for c in candidates:
                if c.exists() and c.is_file():
                    p = c
                    break

        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding='utf-8', errors='ignore')
                resolved_files_content.append(f"\n\n--- [Skill/File Context: {p.name}] ---\n{content}\n----------------------------")
                clean_prompt = clean_prompt.replace(f"@[{path_str}]", f"[File: {p.name}]")
                clean_prompt = clean_prompt.replace(f"@{path_str}", f"[File: {p.name}]")
                clean_prompt = clean_prompt.replace(f"@\"{path_str}\"", f"[File: {p.name}]")
            except Exception as e:
                resolved_files_content.append(f"\n\n--- [File: {p.name} - Error reading: {str(e)}] ---")
                
    if resolved_files_content:
        clean_prompt += "\n" + "\n".join(resolved_files_content)
        
    return clean_prompt, file_paths


# ----------------------------------------------------------------------
# Theme — dark, cyan/violet accents, close to Codex/Gemini CLI aesthetics
# ----------------------------------------------------------------------
APP_CSS = """
Screen {
    background: #0d1117;
    color: #c9d1d9;
}

Header {
    background: #161b22;
    color: #58a6ff;
    text-style: bold;
}

Footer {
    background: #161b22;
    color: #8b949e;
}

#chat-log {
    background: #0d1117;
    border: round #30363d;
    padding: 1 2;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #58a6ff;
}

#chat-log:focus {
    border: round #58a6ff;
}

#status-bar {
    height: 1;
    background: #161b22;
    color: #8b949e;
    padding: 0 2;
}

#status-bar .on {
    color: #3fb950;
    text-style: bold;
}

#status-bar .off {
    color: #f85149;
}

#input-row {
    height: 3;
    background: #161b22;
    border: round #30363d;
}

#input-row:focus-within {
    border: round #58a6ff;
}

#attachment-strip {
    height: auto;
    max-height: 10;
    background: #0d1117;
    padding: 0 1;
    display: none;
}

.chip {
    width: auto;
    height: auto;
    border: round #30363d;
    background: #161b22;
    padding: 0 1;
    margin: 0 1 1 0;
}

.chip-thumb {
    width: auto;
    height: auto;
}

.chip-label {
    width: auto;
    color: #8b949e;
    text-align: center;
}

.chip-file-icon {
    width: 12;
    height: 4;
    content-align: center middle;
    color: #d29922;
    background: #0d1117;
    border: round #30363d;
}

#prompt-icon {
    width: 3;
    content-align: center middle;
    color: #58a6ff;
    text-style: bold;
}

#user-input {
    background: #161b22;
    border: none;
    color: #c9d1d9;
}

#user-input:focus {
    background: #161b22;
}

/* ── Conversation Sidebar ───────────────────────────── */
#conv-sidebar {
    width: 28;
    background: #0d1117;
    border-left: solid #30363d;
    padding: 0;
}

#conv-sidebar.hidden {
    display: none;
}

#sidebar-header {
    height: 3;
    background: #161b22;
    border-bottom: solid #30363d;
    padding: 0 1;
    align: left middle;
}

#new-chat-btn {
    width: 1fr;
    height: 3;
    background: #1f6feb;
    color: #ffffff;
    border: none;
    text-style: bold;
    content-align: center middle;
}

#new-chat-btn:hover {
    background: #388bfd;
}

#conv-list {
    background: #0d1117;
    padding: 0;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #58a6ff;
}

.conv-item {
    height: 4;
    padding: 0 1;
    background: #0d1117;
    border-bottom: solid #21262d;
}

.conv-item:hover {
    background: #161b22;
}

.conv-item.active {
    background: #1c2128;
    border-left: solid #58a6ff;
}

.conv-title {
    color: #c9d1d9;
    height: 2;
    padding: 0 0;
}

.conv-title.active-title {
    color: #58a6ff;
    text-style: bold;
}

.conv-meta {
    color: #6e7681;
    height: 1;
}

.section-title {
    color: #58a6ff;
    text-style: bold;
    margin-top: 1;
}
"""


def format_upload_error(e: Exception) -> str:
    """Fixed"""
    msg = f"[red]upload failed:[/red] {e}\n"
    tb_last = traceback.format_exc().strip().splitlines()[-3:]
    msg += "[dim]" + "\n".join(tb_last) + "[/dim]\n"
    if "NoneType" in str(e) or "NoneType" in repr(e):
        msg += (
            "[yellow]Hint:[/yellow] this usually means DeepSeek's API returned an "
            "unexpected/empty response — often a stale Cloudflare session. Try running "
            "[bold]python dsk/bypass.py[/bold] again to refresh cookies, then /new."
        )
    return msg


class StatusBar(Static):
    """Single-line live status, like Gemini CLI's footer info bar."""

    thinking_on = reactive(True)
    search_on = reactive(False)
    mcp_on = reactive(True)
    mcp_tools = reactive(0)
    n_files = reactive(0)
    n_images = reactive(0)
    session_id = reactive("")
    working = reactive(False)        # True saat tool sedang dieksekusi
    working_tool = reactive("")     # nama tool yang sedang jalan

    def render(self) -> Text:
        t = Text()
        # Working indicator — paling atas, paling mencolok
        if self.working:
            t.append("⚙ ", style="bold #f0c040")
            t.append(f"working ({self.working_tool})  ", style="bold #f0c040")
        t.append("● ", style="#3fb950" if self.thinking_on else "#f85149")
        t.append("thinking ", style="bold" if self.thinking_on else "dim")
        t.append("  ")
        t.append("● ", style="#3fb950" if self.search_on else "#f85149")
        t.append("search ", style="bold" if self.search_on else "dim")
        t.append("  ")
        t.append("● ", style="#3fb950" if (self.mcp_on and self.mcp_tools > 0) else "#f85149")
        t.append(f"mcp ({self.mcp_tools} tools) ", style="bold" if (self.mcp_on and self.mcp_tools > 0) else "dim")
        t.append("  ")
        if self.n_files:
            t.append(f"📎 {self.n_files} files  ", style="#d29922")
        if self.n_images:
            t.append(f"🖼 {self.n_images} images  ", style="#d29922")
        t.append(f"session: {self.session_id[:12]}", style="dim")
        return t


class ConversationItem(Static):
    """Clickable row in the conversation list sidebar."""

    class Selected(Message):
        """Posted when this conversation is clicked."""
        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(self, session_id: str, title: str, updated: str, active: bool = False) -> None:
        super().__init__(classes="conv-item" + (" active" if active else ""))
        self._session_id = session_id
        self._title = title
        self._updated = updated
        self._active = active

    def compose(self) -> ComposeResult:
        title_cls = "conv-title" + (" active-title" if self._active else "")
        short = self._title[:24] + "…" if len(self._title) > 25 else self._title
        yield Static(short or "New chat", classes=title_cls)
        yield Static(self._updated, classes="conv-meta")

    def on_click(self) -> None:
        self.post_message(self.Selected(self._session_id))


class ConvSidebar(Vertical):
    """Conversation list panel — mirrors the Claude/Gemini sidebar."""

    def compose(self) -> ComposeResult:
        yield Button("＋  New Chat", id="new-chat-btn")
        yield VerticalScroll(id="conv-list")

    def refresh_list(
        self,
        conversations: list[dict],
        active_id: str,
    ) -> None:
        """Re-populate the list with fresh conversation data."""
        conv_list = self.query_one("#conv-list", VerticalScroll)
        conv_list.remove_children()
        if not conversations:
            conv_list.mount(Static("[dim]No conversations yet.[/dim]", markup=True))
            return
        items = []
        for c in conversations:
            sid = c.get("id", "")
            title = c.get("title") or c.get("subject") or "New chat"
            ts = c.get("updated_at") or c.get("inserted_at") or ""
            # format timestamp nicely
            try:
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone()
                updated = dt.strftime("%b %d, %H:%M")
            except Exception:
                updated = str(ts)[:16]
            items.append(ConversationItem(sid, title, updated, active=(sid == active_id)))
        conv_list.mount(*items)


class AttachmentChip(Horizontal):
    """Small thumbnail/file chip shown above the input box — like Claude/Gemini compose preview."""

    def __init__(self, path: str | None, label: str, is_file: bool = False):
        super().__init__(classes="chip")
        self.path = path
        self.label_text = label
        self.is_file = is_file

    def compose(self) -> ComposeResult:
        if self.is_file or self.path is None:
            yield Static("📄\n" + self._short(self.label_text), classes="chip-file-icon")
        else:
            yield Vertical(
                Static(render_image_preview(self.path, CHIP_MAX_WIDTH), classes="chip-thumb"),
                Static(self._short(self.label_text), classes="chip-label"),
            )

    @staticmethod
    def _short(name: str, n: int = 14) -> str:
        return name if len(name) <= n else name[: n - 1] + "…"


class ChatInput(Input):
    """Input box that checks the OS clipboard for an image *before* doing a normal text paste.

    Terminals forward Ctrl+V as a bracketed-paste of plain text only, and Textual's
    base Input inserts that text immediately — which is why pasting an image used to
    dump garbage characters into the field. Here we peek at the real OS clipboard
    first; if it holds an image, we hand off to the app's image-paste flow instead
    of touching the text field at all.
    """

    def action_paste(self) -> None:
        """Prevent double paste: Textual's Input.action_paste() pastes from internal clipboard
        while the terminal's bracketed paste (events.Paste) simultaneously pastes OS clipboard,
        causing text to appear duplicated. We let _on_paste handle it exclusively."""
        pass

    def _on_paste(self, event: events.Paste) -> None:
        if ImageGrab is not None and Image is not None:
            try:
                clip = ImageGrab.grabclipboard()
            except Exception:
                clip = None
            if isinstance(clip, Image.Image):
                event.stop()
                event.prevent_default()
                app = self.app
                if isinstance(app, DeepSeekApp):
                    app.paste_clipboard()
                return

        # If multi-line text is pasted, Textual's default Input._on_paste discards
        # everything after the first line (line = event.text.splitlines()[0]).
        # Instead, attach the full multi-line text cleanly as an attached context file!
        if event.text and "\n" in event.text.strip():
            event.stop()
            event.prevent_default()
            app = self.app
            if isinstance(app, DeepSeekApp):
                lines = event.text.strip().splitlines()
                app.attached_files.append(("pasted_text.txt", event.text.strip()))
                app.sync_status()
                log = app.query_one("#chat-log", RichLog)
                log.write(f"[green]📎 Attached multi-line text[/green] ({len(event.text)} chars, {len(lines)} lines)")
                log.write("[dim]Teks panjang berhasil dilampirkan. Anda bisa ketik perintah lalu Enter (atau langsung tekan Enter).[/dim]")
            return

        super()._on_paste(event)
        event.stop()


class DeepSeekApp(App):
    CSS = APP_CSS
    TITLE = "DeepSeek"
    SUB_TITLE = "interactive client"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_log", "Clear log"),
        Binding("ctrl+t", "toggle_thinking", "Toggle thinking"),
        Binding("ctrl+s", "toggle_search", "Toggle search"),
        Binding("ctrl+v", "paste_clipboard", "Paste image"),
        Binding("ctrl+y", "copy_last_response", "Copy last reply"),
        Binding("ctrl+b", "toggle_sidebar", "Toggle sidebar"),
        Binding("ctrl+m", "toggle_mcp", "Toggle MCP"),
    ]

    thinking_enabled = reactive(True)
    search_enabled = reactive(False)
    mcp_enabled = reactive(True)

    def __init__(self):
        super().__init__()
        self.api: DeepSeekAPI | None = None
        self.session_id: str = ""
        self.attached_files: list[tuple[str, str]] = []
        self.attached_images: list[tuple[str, str]] = []
        self.last_response: str = ""
        self.conversations: list[dict] = []  # cached conversation list
        self._sidebar_visible: bool = True
        # local history cache: {session_id: [(role, content, ts), ...]}
        self._history: dict[str, list[tuple[str, str, str]]] = {}
        self._parent_message_ids: dict[str, str] = {}
        self.parent_message_id: str | None = None
        self._tool_call_depth = 0
        self.mcp_manager = None
        self.current_target: str = ""
        self.session_skills: dict[str, list[str]] = {}

    # ---------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="main-panel"):
                yield RichLog(id="chat-log", wrap=True, markup=True, highlight=True)
                yield StatusBar(id="status-bar")
                yield Horizontal(id="attachment-strip")
                with Horizontal(id="input-row"):
                    yield Static("›", id="prompt-icon")
                    yield ChatInput(placeholder="Ask DeepSeek… (Ctrl+B = sidebar, Ctrl+M = toggle MCP, Ctrl+V = paste)", id="user-input")
            yield ConvSidebar(id="conv-sidebar")
        yield Footer()

    # ---------------------------------------------------------- lifecycle
    def on_mount(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(Panel.fit(
            "[bold cyan]DEEPSEEK INTERACTIVE[/bold cyan]\n"
            "[dim]textual client — hold Shift+drag to select text, "
            "or Ctrl+Y / /copy to copy the last reply[/dim]",
            border_style="cyan",
        ))
        self.query_one("#user-input", ChatInput).focus()
        self.init_api()

    @work(exclusive=True, thread=True)
    def init_api(self) -> None:
        token = os.getenv("DEEPSEEK_AUTH_TOKEN") or os.getenv("DEEPSEEK_API_KEY")
        log = self.query_one("#chat-log", RichLog)
        if not token:
            self.call_from_thread(log.write, "[bold red]Error:[/bold red] DEEPSEEK_AUTH_TOKEN not set in .env")
            return
        try:
            self.api = DeepSeekAPI(token)
            self.session_id = self.api.create_chat_session()
            status = self.query_one(StatusBar)
            self.call_from_thread(setattr, status, "session_id", self.session_id)
            self.call_from_thread(log.write, f"[green]✓ session created[/green]  [dim]{self.session_id}[/dim]")
            # load conversation list after init
            self.load_conversations()
            # load MCP servers in background
            self.load_mcp_servers()
        except Exception as e:
            self.call_from_thread(log.write, f"[bold red]Failed to start session:[/bold red] {e}")

    @work(thread=True)
    def load_mcp_servers(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        self.call_from_thread(log.write, "[dim]🔌 Initialising MCP servers...[/dim]")
        try:
            if hasattr(self, "mcp_manager") and self.mcp_manager:
                try:
                    self.mcp_manager.close()
                except Exception:
                    pass
            self.mcp_manager = MCPManager()

            active = self.mcp_manager.load_servers()
            if active:
                self.call_from_thread(
                    log.write,
                    f"[green]✓ MCP connected to {len(active)} servers:[/green] {', '.join(active)} "
                    f"[dim]({len(self.mcp_manager.tools)} tools loaded. Press Ctrl+M to toggle, or type /mcp)[/dim]"
                )
            else:
                self.call_from_thread(log.write, "[dim]No external MCP servers loaded.[/dim]")
            self.call_from_thread(self.sync_status)
        except Exception as e:
            self.call_from_thread(log.write, f"[red]MCP initialisation error: {e}[/red]")

    # ---------------------------------------------------------- helpers
    def sync_status(self) -> None:
        status = self.query_one(StatusBar)
        status.thinking_on = self.thinking_enabled
        status.search_on = self.search_enabled
        status.mcp_on = self.mcp_enabled
        status.mcp_tools = len(self.mcp_manager.tools) if hasattr(self, "mcp_manager") else 0
        status.n_files = len(self.attached_files)
        status.n_images = len(self.attached_images)
        self.rebuild_attachment_strip()

    def rebuild_attachment_strip(self) -> None:
        """Rebuild the small thumbnail chips shown above the input box."""
        strip = self.query_one("#attachment-strip", Horizontal)
        strip.remove_children()
        chips = [AttachmentChip(p, Path(p).name) for p, _fid in self.attached_images]
        chips += [AttachmentChip(None, n, is_file=True) for n, _c in self.attached_files]
        if chips:
            strip.mount(*chips)
            strip.styles.display = "block"
        else:
            strip.styles.display = "none"

    def action_toggle_mcp(self) -> None:
        self.mcp_enabled = not self.mcp_enabled
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[cyan]ℹ MCP tools: {'ENABLED' if self.mcp_enabled else 'DISABLED'}[/cyan]")
        self.sync_status()

    def show_mcp_status(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write("\n[bold cyan]🤖 MCP (Model Context Protocol) status:[/bold cyan]")
        if not self.mcp_manager.sessions:
            log.write("[dim]No active MCP servers connected. (Make sure you configured them in claude_desktop_config.json)[/dim]")
            return
        
        log.write(f"[green]✓ Connected to {len(self.mcp_manager.sessions)} MCP servers:[/green]")
        for name in self.mcp_manager.sessions:
            log.write(f"  - [bold]{name}[/bold]")
            
        log.write(f"\n[green]Available tools ({len(self.mcp_manager.tools)}):[/green]")
        for tool_name, (server_name, t) in self.mcp_manager.tools.items():
            log.write(f"  - [bold yellow]{tool_name}[/bold yellow] (from {server_name}): {t.description}")

    def unmount(self) -> None:
        if hasattr(self, "mcp_manager"):
            self.mcp_manager.close()
        super().unmount()

    def action_toggle_thinking(self) -> None:
        self.thinking_enabled = not self.thinking_enabled
        self.sync_status()

    def action_toggle_search(self) -> None:
        self.search_enabled = not self.search_enabled
        self.sync_status()

    def action_clear_log(self) -> None:
        self.query_one("#chat-log", RichLog).clear()

    def action_toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        sidebar = self.query_one("#conv-sidebar", ConvSidebar)
        sidebar.styles.display = "block" if self._sidebar_visible else "none"

    # ---------------------------------------------------------- conversation sidebar events
    def _write_renderables(self, renderables: list) -> None:
        log = self.query_one("#chat-log", RichLog)
        for r in renderables:
            log.write(r)

    def on_conversation_item_selected(self, event: ConversationItem.Selected) -> None:
        """User clicked a conversation — switch to it and replay history asynchronously."""
        if event.session_id == self.session_id:
            return  # already active
        self.session_id = event.session_id
        self.parent_message_id = self._parent_message_ids.get(self.session_id)
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        self.attached_files.clear()
        self.attached_images.clear()
        status = self.query_one(StatusBar)
        status.session_id = self.session_id
        self.sync_status()

        # refresh sidebar highlight
        sidebar = self.query_one("#conv-sidebar", ConvSidebar)
        sidebar.refresh_list(self.conversations, self.session_id)

        history = self._history.get(self.session_id, [])
        if history:
            log.write(f"[dim]↩ loading conversation ({len(history)} messages)…[/dim]")
            self._render_cached_history(self.session_id, history)
        else:
            log.write(f"[dim]↩ switched to session {self.session_id[:16]}…[/dim]")
            log.write("[dim]loading history from DeepSeek…[/dim]")
            self._fetch_remote_history(self.session_id)

    @work(thread=True)
    def _render_cached_history(self, session_id: str, history: list) -> None:
        """Render cached history in worker thread in progressive batches."""
        def is_system_instruction(content: str) -> bool:
            markers = [
                "=== SYSTEM INSTRUCTION: LOCAL TOOLS AVAILABLE ===",
                "You have access to the following local tools",
                "To call a tool, you MUST output a single valid JSON block"
            ]
            return any(m in content for m in markers)

        filtered = [(role, content, ts) for role, content, ts in history if not is_system_instruction(content)]
        log = self.query_one("#chat-log", RichLog)

        batches = []
        current_batch = []
        for role, content, ts in filtered:
            items = []
            if role == "user":
                items.append(f"\n[bold #58a6ff]you[/bold #58a6ff] [dim]{ts}[/dim]")
                items.append(Text(content, style="#c9d1d9"))
            elif role == "assistant":
                items.append(f"\n[bold #3fb950]deepseek[/bold #3fb950] [dim]{ts}[/dim]")
                renderables = render_latex_in_text(content)
                if len(renderables) == 1 and isinstance(renderables[0], Text):
                    items.append(Markdown(content))
                else:
                    items.extend(renderables)
            elif role == "thinking":
                items.append(Panel(content, title="reasoning", border_style="grey50", title_align="left"))

            current_batch.extend(items)
            if len(current_batch) >= 8:
                batches.append(current_batch)
                current_batch = []

        if current_batch:
            batches.append(current_batch)

        if self.session_id != session_id:
            return

        self.call_from_thread(log.clear)
        for batch in batches:
            if self.session_id != session_id:
                return
            self.call_from_thread(self._write_renderables, batch)
            time.sleep(0.01)

    @work(thread=True)
    def _fetch_remote_history(self, session_id: str) -> None:
        """Fetch message history from DeepSeek API and render in chat log without freezing UI."""
        if self.api is None:
            return
        try:
            messages = self.api.get_chat_history(session_id)
        except Exception:
            messages = []
        log = self.query_one("#chat-log", RichLog)
        if not messages:
            if self.session_id == session_id:
                self.call_from_thread(log.write, "[dim](no history found for this session)[/dim]")
            return

        from datetime import datetime, timezone

        batches = []
        current_batch = []
        parsed_history = []

        for msg in messages:
            if self.session_id != session_id:
                return
            role = (msg.get('role') or '').lower()
            inserted_at = msg.get('inserted_at')
            if inserted_at:
                try:
                    ts = datetime.fromtimestamp(float(inserted_at), tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    ts = ''
            else:
                ts = ''

            content = msg.get('content') or ''
            thinking_content = msg.get('thinking_content') or ''
            thinking_elapsed = msg.get('thinking_elapsed_secs')

            if not content and not thinking_content:
                fragments = msg.get('fragments') or []
                for frag in fragments:
                    ftype = frag.get('type', '')
                    if ftype in ('REQUEST', 'RESPONSE') and not content:
                        content = frag.get('content', '')
                    elif ftype == 'THINK' and not thinking_content:
                        thinking_content = frag.get('content', '')
                        thinking_elapsed = thinking_elapsed or frag.get('elapsed_secs')

            items = []
            if role == 'user':
                for marker in [
                    '\n\n=== SYSTEM INSTRUCTION: LOCAL TOOLS AVAILABLE ===',
                    '\n\n=== SYSTEM INSTRUCTIONS & FORMATTING DIRECTIVES ===',
                ]:
                    idx = content.find(marker)
                    if idx != -1:
                        content = content[:idx]
                content = content.strip()
                if content:
                    items.append(f"\n[bold #58a6ff]you[/bold #58a6ff] [dim]{ts}[/dim]")
                    items.append(Text(content, style="#c9d1d9"))
                    parsed_history.append(('user', content, ts))

            elif role == 'assistant':
                if thinking_content or content:
                    items.append(f"\n[bold #3fb950]deepseek[/bold #3fb950] [dim]{ts}[/dim]")
                if thinking_content:
                    elapsed_str = ''
                    if thinking_elapsed:
                        try:
                            elapsed_str = f" ({float(thinking_elapsed):.1f}s)"
                        except Exception:
                            pass
                    items.append(Panel(
                        thinking_content,
                        title=f"reasoning{elapsed_str}",
                        border_style="grey50",
                        title_align="left"
                    ))
                if content:
                    renderables = render_latex_in_text(content)
                    if len(renderables) == 1 and isinstance(renderables[0], Text):
                        items.append(Markdown(content))
                    else:
                        items.extend(renderables)
                    parsed_history.append(('assistant', content, ts))

            if items:
                current_batch.extend(items)
                if len(current_batch) >= 8:
                    batches.append(current_batch)
                    current_batch = []

        if current_batch:
            batches.append(current_batch)

        if self.session_id != session_id:
            return

        self._history[session_id] = parsed_history
        self.call_from_thread(log.clear)

        for batch in batches:
            if self.session_id != session_id:
                return
            self.call_from_thread(self._write_renderables, batch)
            time.sleep(0.01)

    def on_button_pressed(self, event) -> None:
        if event.button.id == "new-chat-btn":
            self.new_session()

    @work(thread=True)
    def load_conversations(self) -> None:
        """Fetch conversation list from API and refresh sidebar."""
        if self.api is None:
            return
        try:
            convs = self.api.get_chat_sessions()
            self.conversations = convs
            sidebar = self.query_one("#conv-sidebar", ConvSidebar)
            self.call_from_thread(sidebar.refresh_list, convs, self.session_id)
        except Exception:
            pass  # sidebar stays empty, non-fatal

    def action_paste_clipboard(self) -> None:
        self.paste_clipboard()

    def action_copy_last_response(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        if not self.last_response:
            log.write("[yellow]Nothing to copy yet.[/yellow]")
            return
        if pyperclip is None:
            log.write("[red]pyperclip not installed — run: pip install pyperclip --break-system-packages[/red]")
            return
        try:
            pyperclip.copy(self.last_response)
            log.write("[green]✓ last response copied to clipboard[/green]")
        except Exception as e:
            log.write(f"[red]copy failed: {e}[/red] (no clipboard utility found — install xclip/xsel on Linux)")

    @work(thread=True)
    def paste_clipboard(self) -> None:
        """Grab whatever is on the clipboard: image -> chip+upload, text -> attach as text."""
        log = self.query_one("#chat-log", RichLog)
        if ImageGrab is None:
            self.call_from_thread(log.write, "[red]Pillow not installed — cannot read clipboard image.[/red]")
            return
        try:
            img = ImageGrab.grabclipboard()
        except Exception as e:
            self.call_from_thread(log.write, f"[red]Clipboard error: {e}[/red]")
            return

        if Image is not None and isinstance(img, Image.Image):
            # Use a unique filename to avoid overwriting previous clipboard pastes
            from datetime import datetime
            unique_name = f"temp_clipboard_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            temp_path = Path(unique_name)
            try:
                img.save(temp_path, "PNG")
            except Exception as e:
                self.call_from_thread(log.write, f"[red]Failed saving clipboard image: {e}[/red]")
                return
            self.attached_images.append((str(temp_path), ""))  # placeholder until uploaded
            self.call_from_thread(self.sync_status)
            self.call_from_thread(log.write, "[cyan]📋 image pasted — uploading…[/cyan]")
            try:
                self.call_from_thread(log.write, "[dim]⏳ processing image…[/dim]")
                file_id = self.api.upload_file(str(temp_path)) if self.api else None
                if file_id:
                    self.attached_images[-1] = (str(temp_path), file_id)
                    self.call_from_thread(log.write, f"[green]✓ ready[/green] (image_{len(self.attached_images)-1})")
                else:
                    self.attached_images.pop()
                    self.call_from_thread(self.sync_status)
            except Exception as e:
                self.attached_images.pop()
                self.call_from_thread(self.sync_status)
                self.call_from_thread(log.write, format_upload_error(e))

        elif isinstance(img, list):
            for path_str in img:
                p = Path(path_str)
                if not (p.exists() and p.is_file()):
                    continue
                if p.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
                    self.call_from_thread(log.write, f"[cyan]📋 image file: {p.name} — uploading…[/cyan]")
                    try:
                        file_id = self.api.upload_file(str(p)) if self.api else None
                        if file_id:
                            self.attached_images.append((str(p), file_id))
                            self.call_from_thread(self.sync_status)
                            self.call_from_thread(log.write, f"[green]✓ attached[/green] {p.name}")
                    except Exception as e:
                        self.call_from_thread(log.write, format_upload_error(e))
                else:
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        self.attached_files.append((p.name, content))
                        self.call_from_thread(self.sync_status)
                        self.call_from_thread(log.write, f"[green]📎 attached[/green] {p.name}")
                    except Exception as e:
                        self.call_from_thread(log.write, f"[red]failed reading {p.name}: {e}[/red]")

        elif isinstance(img, str) and img.strip():
            # If focused on input box, do not also attach text as a file to prevent duplicate paste
            try:
                chat_input = self.query_one("#user-input", ChatInput)
                if self.focused == chat_input:
                    return
            except Exception:
                pass
            self.attached_files.append(("clipboard_text", img))
            self.call_from_thread(self.sync_status)
            self.call_from_thread(log.write, f"[green]📎 attached clipboard text[/green] ({len(img)} chars)")
        else:
            self.call_from_thread(log.write, "[yellow]Clipboard has no supported image/file/text.[/yellow]")

    # ---------------------------------------------------------- input handling
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            if self.attached_files or self.attached_images:
                text = "Target/scope terlampir. Lakukan autonomous security assessment end-to-end: surface recon, endpoint/asset discovery, analisis celah keamanan, hingga verifikasi temuan. Segera eksekusi tool MCP pertama sekarang secara otonom tanpa menunggu intervensi manual."
            else:
                return
        self.handle_command(text)

    def handle_command(self, user_input: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        low = user_input.lower()

        if low == "/exit":
            self.exit()
            return
        if low in ("/thinking", "/t"):
            self.action_toggle_thinking()
            return
        if low in ("/search", "/s"):
            self.action_toggle_search()
            return
        if low == "/clear":
            self.attached_files.clear()
            self.attached_images.clear()
            self.sync_status()
            log.write("[yellow]🧹 attachments cleared[/yellow]")
            return
        if low == "/new":
            self.new_session()
            return
        if low.startswith("/file "):
            self.attach_file(user_input[6:].strip().strip('"').strip("'"))
            return
        if low.startswith("/image "):
            self.attach_image(user_input[7:].strip().strip('"').strip("'"))
            return
        if low in ("/paste", "/v"):
            self.paste_clipboard()
            return
        if low in ("/copy", "/y"):
            self.action_copy_last_response()
            return
        if low == "/mcp":
            self.show_mcp_status()
            return
        if low.startswith("/dir "):
            self.change_directory(user_input[5:].strip().strip('"').strip("'"))
            return
        if low in ("/report", "/save", "/executive", "/report-executive"):
            # 1. Compile official Executive Assessment reports per report-executive.md
            tgt = self.current_target or "geolocsys.azuba.tech"
            try:
                from utils.report_generator import generate_executive_reports
                p_path, b_path = generate_executive_reports(tgt)
                log.write(f"\n[bold green]✓ Executive Reports compiled per report-executive.md:[/bold green]")
                log.write(f"  • [bold cyan]PENTEST VERSION:[/bold cyan] {p_path}")
                log.write(f"  • [bold cyan]BOUNTY VERSION:[/bold cyan]  {b_path}")
            except Exception as ex:
                log.write(f"[yellow]Executive report notice: {ex}[/yellow]")

            # 2. Also save raw conversation session transcript
            history = self._history.get(self.session_id, [])
            if history:
                full_text = []
                for role, text, ts in history:
                    if role == "assistant":
                        full_text.append(f"### Assistant [{ts}]\n\n{text}\n")
                    elif role == "user" and not text.startswith("[Tool Result"):
                        full_text.append(f"### User [{ts}]\n\n{text}\n")
                saved_rep = save_local_report(tgt, "\n".join(full_text), self.session_id)
                if saved_rep:
                    log.write(f"[dim]✓ Raw session transcript saved: {saved_rep}[/dim]")
            return

        # Extract target hint if user typed a URL or domain (e.g. azuba.tech)
        domain_match = re.search(r'(?:https?://)?([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?::\d+)?)', user_input)
        if domain_match:
            self.current_target = domain_match.group(1).split(":")[0]

        # normal chat message
        prompt, matched_paths = resolve_tagged_files(user_input)

        # Track active skills for this session so context is not lost across turns
        if self.session_id not in self.session_skills:
            self.session_skills[self.session_id] = []
        for p in matched_paths:
            if p not in self.session_skills[self.session_id]:
                self.session_skills[self.session_id].append(p)

        # If report-executive was activated in this session, keep its directive active
        active_skill_stems = [Path(p).stem.lower() for p in self.session_skills.get(self.session_id, [])]
        if "report-executive" in active_skill_stems and "report-executive" not in [Path(p).stem.lower() for p in matched_paths]:
            prompt += (
                "\n\n[MANDATORY SKILL DIRECTIVE - report-executive active in session:\n"
                "- When producing or completing reports, you MUST strictly follow .agents/skills/report-executive.md.\n"
                "- Generate BOTH 'comprehensive_security_assessment_report.md' (Pentest) and 'comprehensive_security_assessment_report_bounty.md' (Bounty).\n"
                "- Include Executive Summary, Summary by Vulnerability Type (all 8 categories), Network Reconnaissance, and full Burp-ready raw HTTP POC blocks.\n"
                "- Persist via save_deliverable(deliverable_type='REPORT', content=...) and save_deliverable(deliverable_type='BOUNTY', content=...)]"
            )

        if self.attached_files:
            ctx = "\n".join(
                f"\n\n--- [File Context: {n}] ---\n{c}\n----------------------------"
                for n, c in self.attached_files
            )
            prompt += "\n" + ctx

        ts = datetime.now().strftime('%H:%M:%S')
        log.write(f"\n[bold #58a6ff]you[/bold #58a6ff] [dim]{ts}[/dim]")
        log.write(Text(user_input, style="#c9d1d9"))
        # save to local history
        self._history.setdefault(self.session_id, []).append(("user", user_input, ts))
        self.send_message(prompt)

    def change_directory(self, path_str: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        p = Path(path_str).resolve()
        if not p.exists() or not p.is_dir():
            log.write(f"[red]Directory not found or is not a folder: {path_str}[/red]")
            return
        
        try:
            os.chdir(p)
            log.write(f"\n[green]✓ Working directory changed to:[/green] [bold]{p}[/bold]")
            # Close existing MCP sessions and reload with new working directory
            if hasattr(self, "mcp_manager") and self.mcp_manager:
                try:
                    self.mcp_manager.close()
                except Exception as e:
                    log.write(f"[yellow]Warning during MCP close: {e}[/yellow]")
            self.load_mcp_servers()
        except Exception as e:
            log.write(f"[red]Failed to change directory: {e}[/red]")

    def attach_file(self, path_str: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        raw_path = path_str.strip().strip('"').strip("'")
        if raw_path.startswith("/file "):
            raw_path = raw_path[6:].strip().strip('"').strip("'")

        # Check path in cwd, or relative to project root
        p = Path(raw_path)
        if not (p.exists() and p.is_file()):
            proj_root = Path(__file__).resolve().parent.parent
            if (proj_root / raw_path).is_file():
                p = proj_root / raw_path

        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                self.attached_files.append((p.name, content))
                self.sync_status()
                log.write(f"[green]📎 attached[/green] {p.name}")
            except Exception as e:
                log.write(f"[red]failed to read {p.name}: {e}[/red]")
        else:
            log.write(f"[red]file not found: {raw_path}[/red]")

    @work(thread=True)
    def attach_image(self, path_str: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        p = Path(path_str)
        if not (p.exists() and p.is_file()):
            self.call_from_thread(log.write, f"[red]image not found: {path_str}[/red]")
            return
        try:
            self.call_from_thread(log.write, f"[cyan]uploading {p.name}…[/cyan]")
            file_id = self.api.upload_file(str(p))
            self.attached_images.append((str(p), file_id))
            self.call_from_thread(self.sync_status)
            self.call_from_thread(log.write, f"[green]🖼 attached[/green] {p.name}")
        except Exception as e:
            self.call_from_thread(log.write, format_upload_error(e))

    @work(thread=True)
    def new_session(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        try:
            self.session_id = self.api.create_chat_session()
            self.parent_message_id = None
            self._parent_message_ids[self.session_id] = None
            self.attached_files.clear()
            self.attached_images.clear()
            self.call_from_thread(self.sync_status)
            status = self.query_one(StatusBar)
            self.call_from_thread(setattr, status, "session_id", self.session_id)
            self.call_from_thread(log.write, f"[green]✓ new session[/green] [dim]{self.session_id}[/dim]")
            # refresh conversation list
            self.load_conversations()
        except Exception as e:
            self.call_from_thread(log.write, f"[red]failed to start new session: {e}[/red]")

    # ---------------------------------------------------------- helpers: working indicator
    def _set_working(self, is_working: bool, tool_name: str = "") -> None:
        """Update the working status indicator in StatusBar (must be called from main thread via call_from_thread)."""
        status = self.query_one(StatusBar)
        status.working = is_working
        status.working_tool = tool_name

    # ---------------------------------------------------------- streaming (iterative, single-thread)
    @work(thread=True)
    def send_message(self, prompt: str) -> None:
        """
        Main agentic loop — runs entirely in ONE background thread using an iterative
        while-loop instead of recursive calls.  This prevents the 'stops mid-way' bug
        where each recursive @work(thread=True) call spawned a new thread that returned
        immediately, orphaning the continuation.
        """
        log = self.query_one("#chat-log", RichLog)
        if self.api is None:
            self.call_from_thread(log.write, "[red]API not initialised[/red]")
            return

        ref_file_ids = [fid for _, fid in self.attached_images]
        current_prompt = prompt
        depth = 0
        MAX_DEPTH = 40

        # Clear attachments now (before the loop)
        attach_files_snapshot = list(self.attached_files)
        self.attached_files.clear()
        self.attached_images = [
            (p, fid) for p, fid in self.attached_images if "temp_clipboard" not in p
        ]
        self.attached_images.clear()
        self.call_from_thread(self.sync_status)

        while depth <= MAX_DEPTH:
            if depth > 0 and depth > MAX_DEPTH:
                self.call_from_thread(log.write, "[red]⚠️ Batas maksimal tool calls tercapai (40). Berhenti.[/red]")
                break

            # --- Build final prompt with system instructions ---
            if not current_prompt.startswith("[Tool Result for"):
                global_formatting = (
                    "\n\n=== SYSTEM INSTRUCTIONS & FORMATTING DIRECTIVES ===\n"
                    "- Do NOT use ellipsis abbreviations like '...', '(...)', or placeholder blocks inside "
                    "mathematical steps, equations, derivations, or code blocks. Write everything fully.\n"
                    "- Always explain your reasoning step-by-step.\n"
                    "==================================================\n"
                )
                final_prompt = current_prompt + global_formatting
                if self.mcp_enabled and hasattr(self, "mcp_manager") and self.mcp_manager.tools:
                    final_prompt += self.mcp_manager.get_system_prompt()
            else:
                final_prompt = current_prompt
                if self.mcp_enabled and hasattr(self, "mcp_manager") and self.mcp_manager.tools:
                    if hasattr(self.mcp_manager, "get_tool_reminder_prompt"):
                        final_prompt += self.mcp_manager.get_tool_reminder_prompt()

            # --- Print header for this turn ---
            self.call_from_thread(
                log.write,
                f"\n[bold #3fb950]deepseek[/bold #3fb950] [dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
            )

            # --- Stream response ---
            thinking_buf, response_buf = "", ""
            sources_list: list[dict] = []
            thinking_started = False

            try:
                chunks = self.api.chat_completion(
                    self.session_id,
                    final_prompt,
                    parent_message_id=self.parent_message_id,
                    thinking_enabled=self.thinking_enabled,
                    search_enabled=self.search_enabled,
                    ref_file_ids=ref_file_ids if depth == 0 else [],
                )
                for chunk in chunks:
                    if chunk["type"] == "ready":
                        self.parent_message_id = chunk["response_message_id"]
                        self._parent_message_ids[self.session_id] = self.parent_message_id
                    elif chunk["type"] == "thinking":
                        if not thinking_started:
                            self.call_from_thread(log.write, "[dim italic]thinking…[/dim italic]")
                            thinking_started = True
                        thinking_buf += chunk["content"]
                    elif chunk["type"] == "text":
                        response_buf += chunk["content"]
                    elif chunk["type"] == "sources":
                        sources_list.extend(chunk.get("sources", []))

            except Exception as e:
                self.call_from_thread(log.write, f"[bold red]error:[/bold red] {e}")
                break

            # --- Render thinking ---
            if thinking_buf:
                self.call_from_thread(
                    log.write,
                    Panel(thinking_buf.strip(), title="reasoning", border_style="grey50", title_align="left"),
                )
                self._history.setdefault(self.session_id, []).append(
                    ("thinking", thinking_buf.strip(), datetime.now().strftime('%H:%M:%S'))
                )

            # --- Render response ---
            if response_buf:
                self.last_response = response_buf
                clean_display_buf = sanitize_for_display(response_buf)
                renderables = render_latex_in_text(clean_display_buf)
                if len(renderables) == 1 and isinstance(renderables[0], Text):
                    self.call_from_thread(log.write, Markdown(clean_display_buf))
                else:
                    for r in renderables:
                        self.call_from_thread(log.write, r)
                ts = datetime.now().strftime('%H:%M:%S')
                self._history.setdefault(self.session_id, []).append(
                    ("assistant", response_buf, ts)
                )
                if sources_list:
                    lines = ["", "[dim]─── sources ──────────────────────────────────────────[/dim]"]
                    for i, s in enumerate(sources_list, 1):
                        title = s.get("title") or "untitled"
                        url   = s.get("url") or ""
                        lines.append(f"[dim]\\[{i}] [link={url}]{title}[/link][/dim]")
                        if url:
                            lines.append(f"[dim]    {url}[/dim]")
                    self.call_from_thread(log.write, "\n".join(lines))

            # --- Cek apakah ada tool call ---
            tool_info = None
            if self.mcp_enabled and hasattr(self, "mcp_manager"):
                tool_info = extract_tool_call(response_buf)
                if not tool_info and thinking_buf:
                    tool_info = extract_tool_call(thinking_buf)

            if not tool_info:
                # Tidak ada tool call → selesai
                if not response_buf:
                    self.call_from_thread(log.write, "[dim](no response)[/dim]")
                else:
                    # Auto-save substantive report (>200 chars) to laptop
                    if len(response_buf) > 200:
                        saved_rep = save_local_report(self.current_target, response_buf, self.session_id)
                        if saved_rep:
                            self.call_from_thread(
                                log.write,
                                f"\n[bold green]📄 Assessment report saved to laptop:[/bold green] [cyan]{saved_rep}[/cyan]"
                            )
                break  # exit loop

            # --- Eksekusi tool (masih di thread yang sama!) ---
            tool_name, args = tool_info
            args_summary = json.dumps(args, ensure_ascii=False)
            if len(args_summary) > 250:
                args_summary = args_summary[:250] + "... [truncated]"
            args_summary = args_summary.replace("\\n", " ")
            self.call_from_thread(
                log.write,
                f"\n[bold yellow]🔧 Running tool:[/bold yellow] [yellow]{tool_name}[/yellow] "
                f"[dim]{args_summary}[/dim]"
            )
            # Tampilkan working indicator
            self.call_from_thread(self._set_working, True, tool_name)

            tool_result = ""
            try:
                tool_result = self.mcp_manager.call_tool(tool_name, args, target=self.current_target)
            except Exception as err:
                tool_result = f"[ERROR] Tool execution failed: {err}"
                self.call_from_thread(log.write, f"[red]Tool execution error: {err}[/red]")
            finally:
                self.call_from_thread(self._set_working, False)

            # Update target hint if present in tool arguments
            if isinstance(args, dict):
                t_val = args.get("target") or args.get("url") or args.get("domain") or args.get("host")
                if t_val:
                    c_val = re.sub(r"^https?://", "", str(t_val)).split("/")[0].split(":")[0].strip()
                    if c_val:
                        self.current_target = c_val

            # Auto-save tool output locally on laptop!
            saved_file = save_local_tool_log(self.current_target, tool_name, args, tool_result)

            # Tampilkan output dalam Console Panel (bersih, rapi)
            cleaned_output = format_tool_output(tool_result, max_lines=150)
            max_raw = 5000
            # Build panel title
            panel_title = f"[bold green]⬡ {tool_name}[/bold green]"
            if saved_file:
                panel_title += f" [dim](💾 {saved_file})[/dim]"
            # Visual panel in TUI
            from rich.syntax import Syntax
            try:
                # Try to detect JSON output
                parsed = json.loads(tool_result)
                if isinstance(parsed, dict) and ("stdout" in parsed or "stderr" in parsed):
                    # Execution result: unpack stdout and stderr cleanly with REAL linebreaks
                    stdout_str = str(parsed.get("stdout") or "")
                    stderr_str = str(parsed.get("stderr") or "")
                    ret_code = parsed.get("return_code", 0)
                    exec_time = parsed.get("execution_time")

                    body_blocks = []
                    if stdout_str.strip():
                        body_blocks.append(format_tool_output(stdout_str, max_lines=150))
                    if stderr_str.strip():
                        body_blocks.append(f"[red]STDERR:\n{format_tool_output(stderr_str, max_lines=50)}[/red]")
                    if not body_blocks:
                        body_blocks.append("[dim](no output produced)[/dim]")

                    meta_info = f"[dim]status: {'success' if parsed.get('success', True) else 'failed'} | exit: {ret_code}"
                    if exec_time is not None:
                        meta_info += f" | time: {exec_time:.2f}s" if isinstance(exec_time, (int, float)) else f" | time: {exec_time}"
                    meta_info += "[/dim]"

                    full_panel_text = meta_info + "\n" + "\n".join(body_blocks)
                    console_renderable = Text.from_markup(full_panel_text)
                    note = None
                elif isinstance(parsed, dict) and ("status" in parsed or "message" in parsed):
                    # Helper tool result (e.g. deliverable saved, session status)
                    status = parsed.get("status", "info")
                    msg = parsed.get("message", "")
                    d_type = parsed.get("deliverable_type", "")
                    color = "green" if status == "success" else "yellow"
                    txt = f"[{color}]● Status: {status}[/{color}]"
                    if d_type:
                        txt += f" | Deliverable: [bold]{d_type}[/bold]"
                    if msg:
                        txt += f"\n{msg}"
                    if "saved_to" in parsed:
                        for sp in parsed.get("saved_to", []):
                            txt += f"\n  - 💾 [cyan]{sp}[/cyan]"
                    console_renderable = Text.from_markup(txt)
                    note = None
                else:
                    formatted_json = json.dumps(parsed, indent=2, ensure_ascii=False)
                    console_renderable = Syntax(
                        formatted_json[:2000],
                        "json",
                        theme="monokai",
                        word_wrap=True,
                        background_color="#0d1117",
                    )
                    if len(formatted_json) > 2000:
                        note = Text(f"  ... +{len(formatted_json)-2000} chars truncated (full sent to DeepSeek)", style="dim yellow")
                    else:
                        note = None
            except Exception:
                # Plain text — clean and display in monospace with real linebreaks
                console_renderable = Text(cleaned_output, style="#98c379", no_wrap=False)
                if len(tool_result) > max_raw:
                    note = Text(f"  ... +{len(tool_result)-max_raw} chars truncated (full sent to DeepSeek)", style="dim yellow")
                else:
                    note = None

            self.call_from_thread(
                log.write,
                Panel(
                    console_renderable,
                    title=panel_title,
                    border_style="#2ea043",
                    title_align="left",
                    padding=(0, 1),
                )
            )
            if note:
                self.call_from_thread(log.write, note)

            # Simpan ke history
            self._history.setdefault(self.session_id, []).append(
                ("user", f"[Tool Result for '{tool_name}']\n{tool_result}", datetime.now().strftime('%H:%M:%S'))
            )

            # Siapkan follow-up prompt untuk iterasi berikutnya
            current_prompt = (
                f"[Tool Result for '{tool_name}']:\n"
                f"{tool_result}\n\n"
                "CRITICAL INSTRUCTION: Analyze the telemetry above.\n"
                "- Proceed directly to the next logical step using another tool call: "
                "```json {\"tool\": \"...\", \"arguments\": {...}} ```.\n"
                "- If blocked (WAF, 403, Cloudflare) pivot to alternate subdomains, paths, or tools.\n"
                "- Do NOT ask the user. Keep executing autonomously until objective is accomplished."
            )
            depth += 1
            # Loop continues → next iteration sends follow_up


def main():
    DeepSeekApp().run()


if __name__ == "__main__":
    main()
