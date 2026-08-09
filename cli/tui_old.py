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
import re
import traceback
import json
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from mcp_client import MCPManager

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
    # Regex to find @followed by path, handles quotes if path has spaces, e.g. @"file name.txt" or @file.txt
    pattern = r'@(?:"([^"]+)"|([^\s]+))'
    matches = re.findall(pattern, prompt)
    
    file_paths = []
    for m in matches:
        path_str = m[0] if m[0] else m[1]
        file_paths.append(path_str)
        
    resolved_files_content = []
    clean_prompt = prompt
    
    for path_str in file_paths:
        p = Path(path_str)
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding='utf-8', errors='ignore')
                resolved_files_content.append(f"\n\n--- [File Context: {p.name}] ---\n{content}\n----------------------------")
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

    def render(self) -> Text:
        t = Text()
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
        super()._on_paste(event)


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
    def on_conversation_item_selected(self, event: ConversationItem.Selected) -> None:
        """User clicked a conversation — switch to it and replay local history."""
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
        # replay cached history
        history = self._history.get(self.session_id, [])
        # Filter out system instruction messages that might have been stored accidentally
        def is_system_instruction(content: str) -> bool:
            markers = [
                "=== SYSTEM INSTRUCTION: LOCAL TOOLS AVAILABLE ===",
                "You have access to the following local tools",
                "To call a tool, you MUST output a single valid JSON block"
            ]
            return any(m in content for m in markers)
        
        filtered_history = [(role, content, ts) for role, content, ts in history if not is_system_instruction(content)]
        
        if filtered_history:
            for role, content, ts in filtered_history:
                if role == "user":
                    log.write(f"\n[bold #58a6ff]you[/bold #58a6ff] [dim]{ts}[/dim]")
                    log.write(Text(content, style="#c9d1d9"))
                elif role == "assistant":
                    log.write(f"\n[bold #3fb950]deepseek[/bold #3fb950] [dim]{ts}[/dim]")
                    # Render math in assistant messages
                    renderables = render_latex_in_text(content)
                    if len(renderables) == 1 and isinstance(renderables[0], Text):
                        # fallback to Markdown if no math found
                        log.write(Markdown(content))
                    else:
                        for r in renderables:
                            log.write(r)
                elif role == "thinking":
                    log.write(Panel(content, title="reasoning", border_style="grey50", title_align="left"))
        else:
            # No local cache — fetch from API in background
            log.write(f"[dim]↩ switched to session [/dim][dim]{self.session_id[:16]}…[/dim]")
            log.write("[dim]loading history…[/dim]")
            self._fetch_remote_history(self.session_id)
        # refresh sidebar highlight
        sidebar = self.query_one("#conv-sidebar", ConvSidebar)
        sidebar.refresh_list(self.conversations, self.session_id)

    @work(thread=True)
    def _fetch_remote_history(self, session_id: str) -> None:
        """Fetch message history from DeepSeek API and render in chat log."""
        if self.api is None:
            return
        try:
            messages = self.api.get_chat_history(session_id)
        except Exception:
            messages = []
        log = self.query_one("#chat-log", RichLog)
        if not messages:
            self.call_from_thread(log.write, "[dim](no history found for this session)[/dim]")
            return

        def render_messages():
            from datetime import datetime, timezone
            log.clear()
            for msg in messages:
                role = (msg.get('role') or '').lower()  # 'user' or 'assistant'
                # timestamp from inserted_at (Unix float)
                inserted_at = msg.get('inserted_at')
                if inserted_at:
                    try:
                        ts = datetime.fromtimestamp(float(inserted_at), tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
                    except Exception:
                        ts = ''
                else:
                    ts = ''

                # /chat/history_messages returns flat fields: content, thinking_content
                # (fragments field exists but may be empty in this endpoint)
                content = msg.get('content') or ''
                thinking_content = msg.get('thinking_content') or ''
                thinking_elapsed = msg.get('thinking_elapsed_secs')

                # Fallback: parse from fragments if content empty
                if not content and not thinking_content:
                    fragments = msg.get('fragments') or []
                    for frag in fragments:
                        ftype = frag.get('type', '')
                        if ftype in ('REQUEST', 'RESPONSE') and not content:
                            content = frag.get('content', '')
                        elif ftype == 'THINK' and not thinking_content:
                            thinking_content = frag.get('content', '')
                            thinking_elapsed = thinking_elapsed or frag.get('elapsed_secs')

                if role == 'user':
                    # Strip injected system instruction blocks
                    for marker in [
                        '\n\n=== SYSTEM INSTRUCTION: LOCAL TOOLS AVAILABLE ===',
                        '\n\n=== SYSTEM INSTRUCTIONS & FORMATTING DIRECTIVES ===',
                    ]:
                        idx = content.find(marker)
                        if idx != -1:
                            content = content[:idx]
                    content = content.strip()
                    if content:
                        log.write(f"\n[bold #58a6ff]you[/bold #58a6ff] [dim]{ts}[/dim]")
                        log.write(Text(content, style="#c9d1d9"))
                        self._history.setdefault(session_id, []).append(('user', content, ts))

                elif role == 'assistant':
                    if thinking_content or content:
                        log.write(f"\n[bold #3fb950]deepseek[/bold #3fb950] [dim]{ts}[/dim]")
                    if thinking_content:
                        elapsed_str = ''
                        if thinking_elapsed:
                            try:
                                elapsed_str = f" ({float(thinking_elapsed):.1f}s)"
                            except Exception:
                                pass
                        log.write(Panel(
                            thinking_content,
                            title=f"reasoning{elapsed_str}",
                            border_style="grey50",
                            title_align="left"
                        ))
                    if content:
                        renderables = render_latex_in_text(content)
                        if len(renderables) == 1 and isinstance(renderables[0], Text):
                            log.write(Markdown(content))
                        else:
                            for r in renderables:
                                log.write(r)
                        self._history.setdefault(session_id, []).append(('assistant', content, ts))

        self.call_from_thread(render_messages)

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

        # normal chat message
        prompt, _ = resolve_tagged_files(user_input)
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
        p = Path(path_str)
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                self.attached_files.append((p.name, content))
                self.sync_status()
                log.write(f"[green]📎 attached[/green] {p.name}")
            except Exception as e:
                log.write(f"[red]failed to read {p.name}: {e}[/red]")
        else:
            log.write(f"[red]file not found: {path_str}[/red]")

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

    # ---------------------------------------------------------- streaming
    @work(thread=True)
    def send_message(self, prompt: str, _depth: int = 0) -> None:
        log = self.query_one("#chat-log", RichLog)
        if self.api is None:
            self.call_from_thread(log.write, "[red]API not initialised[/red]")
            return

        if _depth > 40:
            self.call_from_thread(log.write, "[red]⚠️ Too many tool calls in a row. Stopping.[/red]")
            return

        ref_file_ids = [fid for _, fid in self.attached_images]
        self.call_from_thread(
            log.write,
            f"\n[bold #3fb950]deepseek[/bold #3fb950] [dim]{datetime.now().strftime('%H:%M:%S')}[/dim]",
        )

        # Inject system instructions and formatting guidelines
        final_prompt = prompt
        if not prompt.startswith("[Tool Result for"):
            global_formatting = (
                "\n\n=== SYSTEM INSTRUCTIONS & FORMATTING DIRECTIVES ===\n"
                "- Do NOT use ellipsis abbreviations like '...', '(...)', or placeholder blocks inside mathematical steps, equations, derivations, or code blocks. You MUST write out all formulas, terms, expressions, and steps fully, completely, and explicitly so they are 100% clear.\n"
                "- Always explain your reasoning step-by-step fully.\n"
                "==================================================\n"
            )
            final_prompt = prompt + global_formatting
            
            # Append MCP system prompt if tools are enabled
            if self.mcp_enabled and hasattr(self, "mcp_manager") and self.mcp_manager.tools:
                final_prompt += self.mcp_manager.get_system_prompt()

        thinking_buf, response_buf = "", ""
        sources_list: list[dict] = []
        thinking_started, response_started = False, False
        try:
            chunks = self.api.chat_completion(
                self.session_id,
                final_prompt,
                parent_message_id=self.parent_message_id,
                thinking_enabled=self.thinking_enabled,
                search_enabled=self.search_enabled,
                ref_file_ids=ref_file_ids,
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
                    if not response_started:
                        response_started = True
                    response_buf += chunk["content"]
                elif chunk["type"] == "sources":
                    sources_list.extend(chunk.get("sources", []))

            if thinking_buf:
                self.call_from_thread(
                    log.write,
                    Panel(thinking_buf.strip(), title="reasoning", border_style="grey50", title_align="left"),
                )
                self._history.setdefault(self.session_id, []).append(
                    ("thinking", thinking_buf.strip(), datetime.now().strftime('%H:%M:%S'))
                )
            if response_buf:
                self.last_response = response_buf
                # Render LaTeX math in response
                renderables = render_latex_in_text(response_buf)
                # If no math blocks detected, fallback to Markdown
                if len(renderables) == 1 and isinstance(renderables[0], Text):
                    # Plain text, render as Markdown
                    self.call_from_thread(log.write, Markdown(response_buf))
                else:
                    # Mixed content: render each part
                    for r in renderables:
                        self.call_from_thread(log.write, r)
                ts = datetime.now().strftime('%H:%M:%S')
                self._history.setdefault(self.session_id, []).append(
                    ("assistant", response_buf, ts)
                )
                # display sources as footnotes
                if sources_list:
                    lines = ["", "[dim]─── sources ──────────────────────────────────────────[/dim]"]
                    for i, s in enumerate(sources_list, 1):
                        title = s.get("title") or "untitled"
                        url   = s.get("url") or ""
                        lines.append(f"[dim]\\[{i}] [link={url}]{title}[/link][/dim]")
                        if url:
                            lines.append(f"[dim]    {url}[/dim]")
                    self.call_from_thread(log.write, "\n".join(lines))
            # Check if DeepSeek requested to execute a tool (MCP mode) in either thinking or response buffer
            combined_buf = thinking_buf + "\n" + response_buf
            tool_called = False

            if self.mcp_enabled and hasattr(self, "mcp_manager") and combined_buf.strip():
                # Look for ```json ... ``` blocks
                json_blocks = re.findall(r'```json\s*\n(.*?)\n```', combined_buf, re.DOTALL)
                if not json_blocks:
                    json_blocks = re.findall(r'```json\s*(.*?)\s*```', combined_buf, re.DOTALL)

                for block in json_blocks:
                    try:
                        tool_data = json.loads(block.strip())
                        if isinstance(tool_data, dict) and "tool" in tool_data:
                            tool_name = tool_data["tool"]
                            args = tool_data.get("arguments", {})

                            self.call_from_thread(
                                log.write,
                                f"\n[bold yellow]🔧 Running tool:[/bold yellow] [yellow]{tool_name}[/yellow] "
                                f"with arguments: [dim]{json.dumps(args)}[/dim]"
                            )

                            # Execute tool
                            self._tool_call_depth += 1
                            tool_result = self.mcp_manager.call_tool(tool_name, args)
                            self._tool_call_depth -= 1

                            # Display snippet of output (visual only in TUI console, full is sent to DeepSeek)
                            max_len = 2500
                            if len(tool_result) > max_len:
                                snippet = tool_result[:max_len] + f"\n\n[yellow]... (visual truncation in TUI console; {len(tool_result) - max_len} more characters sent to DeepSeek) ...[/yellow]"
                            else:
                                snippet = tool_result

                            self.call_from_thread(
                                log.write,
                                f"[bold green]✓ Tool Output:[/bold green]\n[dim]{snippet}[/dim]"
                            )

                            # Save tool execution to history cache
                            self._history.setdefault(self.session_id, []).append(
                                ("user", f"[Tool Result for '{tool_name}']\n{tool_result}", datetime.now().strftime('%H:%M:%S'))
                            )

                            # Auto follow-up to feed tool output to model
                            follow_up = (
                                f"[Tool Result for '{tool_name}']:\n"
                                f"{tool_result}\n\n"
                                f"Please analyze this tool output and provide your final response or call another tool if needed."
                            )
                            self.send_message(follow_up, _depth + 1)
                            tool_called = True
                            break  # Only run one tool call at a time to prevent conflicts
                    except Exception:
                        pass

            if not response_buf and not tool_called:
                self.call_from_thread(log.write, "[dim](no response)[/dim]")

        except Exception as e:
            self.call_from_thread(log.write, f"[bold red]error:[/bold red] {e}")

        # cleanup temp clipboard images if any
        self.attached_images = [
            (p, fid) for p, fid in self.attached_images if "temp_clipboard" not in p
        ]
        # Clear all attachments after sending the message (optional; user can re-add if needed)
        self.attached_files.clear()
        self.attached_images.clear()
        self.call_from_thread(self.sync_status)


def main():
    DeepSeekApp().run()


if __name__ == "__main__":
    main()
