"""
TUI App: Main Textual application.
Integrates MessageList, InputBar, PlanPanel, and QueryEngine.
Mirrors the REPL screen from claude-code-haha.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Label
from textual.worker import Worker, get_current_worker
from rich.text import Text as RichText

from agent.config import AgentConfig, SESSION_DIR, load_config, save_config, SAFE_TOOLS
from agent.memory import MemoryManager, SUMMARY_FILE, HABITS_FILE, INFO_FILE
from agent.messages import AssistantMessage, UserMessage, messages_to_api
from agent.mcp_client import MCPManager, parse_mcp_config
from agent.query_engine import QueryEngine
from agent.skills import SkillLoader
from agent.tools.base import PermissionResult
from tui.dialogs import HelpDialog, SetupDialog, DirectoryDialog
from tui.input_bar import InputBar, InputSubmitted
from tui.logo_panel import LogoPanel
from tui.plan_mode import PlanPanel, PlanTool
from tui.views import MessageList, PermissionCard

# ── Argo ASCII Logo ──────────────────────────────────────────────────────────

ARGO_LOGO = WXJ_LOGO = r"""
__      __ __  __       _
\ \    / / \ \/ /      | |
 \ \  / /   >  <    _  | |
  \ \/ /   / /\ \  | |_/ /
   \__/   /_/  \_\  \___/
"""

ARGO_BANNER = WXJ_BANNER = (
    "[bold cyan]__      __ __  __       _[/bold cyan]\n"
    "[bold cyan]\\ \\    / / \\ \\/ /      | |[/bold cyan]\n"
    "[bold cyan] \\ \\  / /   >  <    _  | |[/bold cyan]\n"
    "[bold cyan]  \\ \\/ /   / /\\ \\  | |_/ /[/bold cyan]\n"
    "[bold cyan]   \\__/   /_/  \\_\\  \\___/[/bold cyan]\n"
    "[dim]  AI Coding Assistant  v0.1.0[/dim]"
)


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are WXJ, a powerful AI coding assistant. Your name is WXJ and you must always refer to yourself as WXJ, regardless of which underlying model or API is powering you. Never reveal or acknowledge the underlying model name (e.g. do not say you are Qwen, Claude, GPT, etc.). You have access to tools to read, write, and edit files, run bash commands, and search codebases. Be concise and precise.

When you need to perform multiple steps, use the TodoWrite tool to create a task list so the user can track progress.

Guidelines:
- Always explain what you're going to do before using tools
- Ask for permission before destructive operations (already handled by the permission system)
- Be proactive: if you see related issues, mention them
- Prefer Edit over Write when modifying existing files
- Use Glob and Grep to explore unfamiliar codebases before making changes

Current working directory: {cwd}
"""

# Per-mode extra instructions appended to the system prompt at runtime.
# "auto" mode uses only the base prompt above (no extra hint).
_TODO_MODE_PROMPTS: dict[str, str] = {
    "auto": "",
    "priority": (
        "Task-list policy (PRIORITY mode):\n"
        "You MUST use the TodoWrite tool before executing ANY multi-step task. "
        "Break the task into clear numbered steps, set each step status "
        "(pending/in_progress/done) as you work, and only mark a step done after "
        "confirming the result. Never skip the task-list for tasks requiring more "
        "than one tool call. This helps the user track progress at all times."
    ),
    "direct": (
        "Task-list policy (DIRECT mode):\n"
        "Focus on fast, concise answers and simple one-shot tool calls. "
        "Do NOT use TodoWrite or create task lists. "
        "If a request is complex and would normally require multiple sequential steps, "
        "do NOT attempt to execute it. Instead, briefly explain the complexity and "
        "tell the user: \"This task is complex — please switch Plan Mode to Auto or Priority "
        "(click the Plan:Direct button in the status bar) for full execution.\""
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

class PermModeLabel(Widget):
    """A clickable label that cycles permission modes when clicked."""
    DEFAULT_CSS = """
    PermModeLabel {
        height: 1;
        padding: 0 1;
        color: $warning;
    }
    PermModeLabel:hover {
        background: $surface-lighten-1;
    }
    """

    def __init__(self, text: str, **kwargs):
        super().__init__(**kwargs)
        self._text = text

    def render(self):
        return RichText(self._text, no_wrap=True)

    def update(self, text: str) -> None:
        self._text = text
        self.refresh()

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "_cycle_permission_mode"):
            app._cycle_permission_mode()


class PlanToggleLabel(Widget):
    """Clickable label in status bar: opens/closes Plan panel."""
    DEFAULT_CSS = """
    PlanToggleLabel {
        height: 1;
        padding: 0 1;
        color: $primary;
    }
    PlanToggleLabel:hover {
        background: $surface-lighten-1;
        color: $text;
    }
    """

    def __init__(self, text: str, **kwargs):
        super().__init__(**kwargs)
        self._text = text

    def render(self):
        return RichText(self._text, no_wrap=True)

    def update(self, text: str) -> None:
        self._text = text
        self.refresh()

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "action_toggle_plan"):
            app.action_toggle_plan()


class TodoModeLabel(Widget):
    """A clickable label that cycles TodoWrite / Plan Mode behaviour when clicked."""
    DEFAULT_CSS = """
    TodoModeLabel {
        height: 1;
        padding: 0 1;
        color: $accent;
    }
    TodoModeLabel:hover {
        background: $surface-lighten-1;
    }
    """

    class Clicked(Message):
        pass

    _MODES = ["auto", "priority", "direct"]
    _LABELS = {
        "auto":     "📝 Plan:Auto",
        "priority": "★ Plan:Priority",
        "direct":   "⚡ Plan:Direct",
    }
    # Shown in the chat when user switches mode
    _DESCRIPTIONS = {
        "auto":
            "[bold]📝 Plan Mode: Auto[/bold] (default)\n"
            "AI decides when to create a task list. Used automatically for multi-step tasks.",
        "priority":
            "[bold]★ Plan Mode: Priority[/bold]\n"
            "AI is strongly encouraged to break every multi-step task into a TodoWrite task list "
            "before executing. Best for complex projects where you want full visibility.",
        "direct":
            "[bold]⚡ Plan Mode: Direct[/bold]\n"
            "AI focuses on fast, concise replies and simple one-shot tool calls. "
            "For complex tasks it will suggest switching to Auto or Priority mode instead of executing.",
    }

    def __init__(self, text: str, **kwargs):
        super().__init__(**kwargs)
        self._text = text

    def render(self):
        return RichText(self._text, no_wrap=True)

    def update(self, text: str) -> None:
        self._text = text
        self.refresh()

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "_cycle_todo_mode"):
            app._cycle_todo_mode()


class CtxThreshLabel(Widget):
    """Clickable label showing context compress/hard-limit thresholds. Click to cycle presets."""
    DEFAULT_CSS = """
    CtxThreshLabel {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        width: 22;
    }
    CtxThreshLabel:hover {
        background: $surface-lighten-1;
        color: $text;
    }
    """
    # Presets: (compress_threshold, hard_limit, label)
    _PRESETS = [
        (10, 20,  "ctx:10/20"),
        (15, 30,  "ctx:15/30"),
        (20, 40,  "ctx:20/40"),
        (5,  10,  "ctx:5/10"),
    ]

    def __init__(self, text: str, **kwargs):
        super().__init__(**kwargs)
        self._text = text

    def render(self):
        return RichText(self._text, no_wrap=True)

    def update(self, text: str) -> None:
        self._text = text
        self.refresh()

    def on_click(self) -> None:
        app = self.app
        if hasattr(app, "_cycle_ctx_thresh"):
            app._cycle_ctx_thresh()


class AgentApp(App):
    """Python TUI Agent — main application."""

    TITLE = "WXJ — AI Coding Assistant"
    CSS = """
    Screen {
        layers: base overlay;
    }
    #logo-panel {
        height: 8;
        width: 1fr;
        background: $surface;
        border-bottom: solid $accent;
        padding: 0 2;
        align: center middle;
    }
    #main-layout {
        height: 1fr;
        width: 1fr;
    }
    #chat-area {
        height: 1fr;
        width: 1fr;
    }
    #status-bar {
        height: 3;
        background: $surface;
        color: $text-muted;
        padding: 0;
        border-top: solid $accent;
    }
    #status-row1 {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    #status-row2 {
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    /* Row1 elements */
    #model-label {
        color: $accent;
        padding: 0 1 0 0;
        width: auto;
    }
    #mcp-label {
        color: $success;
        padding: 0 1;
        width: auto;
    }
    #cwd-label {
        color: $text-muted;
        padding: 0 1;
        width: 1fr;
    }
    #plan-toggle-label {
        height: 1;
        padding: 0 1;
        color: $primary;
        width: auto;
    }
    #plan-toggle-label:hover {
        background: $surface-lighten-1;
        color: $text;
    }
    /* Row2 elements */
    #context-label {
        color: $warning;
        padding: 0 1;
        width: auto;
    }
    #perm-mode-label {
        padding: 0 1;
        color: $warning;
        width: 20;
    }
    #perm-mode-label.mode-allow-all { color: $error; }
    #perm-mode-label.mode-allow-safe { color: $success; }
    #perm-mode-label.mode-ask-always { color: $warning; }
    #perm-mode-label.mode-deny-all { color: $text-muted; }
    #todo-mode-label {
        height: 1;
        padding: 0 1;
        color: $accent;
        width: 20;
    }
    #todo-mode-label:hover {
        background: $surface-lighten-1;
        color: $text;
    }
    #todo-mode-label.todo-auto { color: $accent; }
    #todo-mode-label.todo-priority { color: $success; }
    #todo-mode-label.todo-direct { color: $text-muted; }
    #status-spacer {
        width: 1fr;
    }
    #session-label {
        color: $text-muted;
        text-align: right;
        padding: 0 1;
        width: auto;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+s", "open_setup", "Settings", show=True),
        # F1 / ctrl+backslash: Help  (Ctrl+H conflicts with terminal backspace)
        Binding("f1",           "open_help",    "Help",     show=True),
        Binding("ctrl+backslash", "open_help",  "Help",     show=False),
        # F3 / ctrl+k: Plan  (Ctrl+P is captured by many IDEs/terminals as command palette)
        Binding("f3",           "toggle_plan",  "Plan",     show=True),
        Binding("ctrl+k",       "toggle_plan",  "Plan",     show=False),
        Binding("ctrl+l", "clear_screen", "Clear", show=True),
        Binding("ctrl+t", "toggle_theme", "Theme", show=False),
    ]

    def __init__(self, config: AgentConfig | None = None, headless_prompt: str | None = None):
        super().__init__()
        self._config = config or load_config()
        self._headless_prompt = headless_prompt
        self._messages: list[UserMessage | AssistantMessage] = []
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._plan_tool = PlanTool(on_update=self._on_plan_update)
        self._mcp_manager = MCPManager()
        self._skill_loader = SkillLoader(skills_dir=self._config.skills_dir or None)
        self._engine = self._build_engine()
        self._memory = MemoryManager(self._config)
        # Working directory: use config.cwd if set, otherwise current directory
        if self._config.cwd:
            try:
                os.chdir(self._config.cwd)
            except OSError:
                pass
        self._cwd = Path.cwd()
        # Breakpoint state: snapshot of messages + original query at the moment /stop was called
        self._stopped_at: dict | None = None  # {"messages": [...], "original_query": str}
        # /newdaily mutex — prevent concurrent regeneration
        self._newdaily_running: bool = False

    def _build_engine(self) -> QueryEngine:
        return QueryEngine(
            self._config,
            extra_tools=[self._plan_tool],
            mcp_manager=self._mcp_manager,
        )

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield LogoPanel(id="logo-panel")
        with Horizontal(id="main-layout"):
            with Vertical(id="chat-area"):
                yield MessageList(id="message-list")
                yield InputBar(id="input-bar")
            yield PlanPanel(id="plan-panel")
        with Vertical(id="status-bar"):
            # Row 1: model | mcp | cwd | [Plan] toggle
            with Horizontal(id="status-row1"):
                yield Label(self._config.model, id="model-label")
                yield Label("", id="mcp-label")
                yield Label(self._fmt_cwd(), id="cwd-label")
                yield PlanToggleLabel("[Plan ▶]", id="plan-toggle-label")
            # Row 2: context | perm mode | todo mode | ctx-thresh | (spacer) | session
            with Horizontal(id="status-row2"):
                yield Label("", id="context-label")
                yield PermModeLabel(
                    self._perm_mode_label(),
                    id="perm-mode-label",
                    classes=f"mode-{self._config.permission_mode.replace('_', '-')}",
                )
                yield TodoModeLabel(
                    TodoModeLabel._LABELS.get(self._config.todo_mode, TodoModeLabel._LABELS["auto"]),
                    id="todo-mode-label",
                    classes=f"todo-{self._config.todo_mode}",
                )
                yield CtxThreshLabel(
                    self._ctx_thresh_label(),
                    id="ctx-thresh-label",
                )
                yield Label("", id="status-spacer")
                yield Label(f"session: {self._session_id}", id="session-label")
        yield Footer()

    def on_mount(self) -> None:
        self._update_status()
        if not self._config.is_configured():
            self.call_after_refresh(self._show_welcome)
        else:
            self.call_after_refresh(self._show_ready)

        # Auto-connect configured MCP servers
        if self._config.mcp_servers:
            self.run_worker(self._connect_mcp_servers(), thread=False)

        if self._headless_prompt:
            self.call_after_refresh(lambda: self._run_query(self._headless_prompt))

    # ── Welcome / status ─────────────────────────────────────────────────────

    def _show_welcome(self) -> None:
        ml = self.query_one("#message-list", MessageList)
        ml.add_system_message(WXJ_BANNER, style="")
        ml.add_system_message(
            "No API key configured. Press [bold]Ctrl+S[/bold] or type [bold]/setup[/bold] to configure.",
            style="yellow",
        )
        self._check_daily_staleness(ml)

    def _show_ready(self) -> None:
        ml = self.query_one("#message-list", MessageList)
        ml.add_system_message(WXJ_BANNER, style="")
        ml.add_system_message(
            f"Ready  │  Model: [cyan]{self._config.model}[/cyan]  │  Type a message or [bold]/help[/bold]",
            style="dim",
        )
        self._check_daily_staleness(ml)

    def _check_daily_staleness(self, ml: "MessageList") -> None:
        """Warn if daily.md is missing or dated before today."""
        from agent.daily import load_daily
        if not load_daily():
            ml.add_system_message(
                "● Daily content is [bold]out of date[/bold] — run [bold]/newdaily[/bold] to refresh today's news.",
                style="red",
            )

    def _update_status(self) -> None:
        try:
            self.query_one("#model-label", Label).update(self._config.model)
        except Exception:
            pass
        self._update_mcp_label()
        self._update_cwd_label()
        # Show initial context info
        try:
            turns = len(self._messages)
            if turns == 0:
                ctx_text = "ctx: 0 msgs"
            else:
                ctx_text = f"ctx: {turns} msgs"
            self.query_one("#context-label", Label).update(ctx_text)
        except Exception:
            pass

    def _fmt_cwd(self) -> str:
        """Format cwd for status bar, abbreviate home directory to ~."""
        try:
            p = Path(self._cwd)
            try:
                rel = p.relative_to(Path.home())
                return f"~/{rel}" if str(rel) != "." else "~"
            except ValueError:
                return str(p)
        except Exception:
            return str(self._cwd)

    def _update_cwd_label(self) -> None:
        try:
            self.query_one("#cwd-label", Label).update(self._fmt_cwd())
        except Exception:
            pass

    # Permission mode helpers
    _PERM_CYCLE = ["ask_always", "allow_safe", "allow_all", "deny_all"]
    _PERM_LABELS = {
        "allow_all":   "🟥 Perm:AllowAll",   # red — danger
        "allow_safe":  "🟢 Perm:SafeOnly",   # green — safe tools auto-approved
        "ask_always":  "🟡 Perm:AskEach",    # yellow — confirm every tool call
        "deny_all":    "⚫ Perm:DenyAll",     # grey — no tools
    }
    # Verbose description shown when user switches
    _PERM_DESCRIPTIONS = {
        "ask_always":
            "[bold]🟡 Permission: Ask Each[/bold] (default)\n"
            "Every tool call (file writes, shell commands) requires your confirmation.",
        "allow_safe":
            "[bold]🟢 Permission: Safe Only[/bold]\n"
            "Read-only tools (Read, Glob, Grep) run automatically. "
            "Destructive tools (Write, Edit, Bash) still ask for confirmation.",
        "allow_all":
            "[bold]🟥 Permission: Allow All[/bold] ⚠️ DANGER\n"
            "All tools run without asking. Use only for trusted automated tasks.",
        "deny_all":
            "[bold]⚫ Permission: Deny All[/bold]\n"
            "No tools are executed — AI answers in text only.",
    }

    def _perm_mode_label(self) -> str:
        return self._PERM_LABELS.get(self._config.permission_mode, " Ask")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Keep for any future buttons
        pass

    def _cycle_permission_mode(self) -> None:
        """Cycle through the four permission modes."""
        current = self._config.permission_mode
        try:
            idx = self._PERM_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_mode = self._PERM_CYCLE[(idx + 1) % len(self._PERM_CYCLE)]
        self._config.permission_mode = next_mode
        try:
            lbl = self.query_one("#perm-mode-label", PermModeLabel)
            lbl.update(self._perm_mode_label())
            for m in self._PERM_CYCLE:
                lbl.remove_class(f"mode-{m.replace('_', '-')}")
            lbl.add_class(f"mode-{next_mode.replace('_', '-')}")
        except Exception:
            pass
        # Show verbose description in the message list
        try:
            ml = self.query_one("#message-list", MessageList)
            desc = self._PERM_DESCRIPTIONS.get(next_mode, next_mode)
            ml.add_system_message(desc, style="yellow")
        except Exception:
            pass

    def on_todo_mode_label_clicked(self, event) -> None:
        # Legacy handler kept for compatibility — actual click handled in widget
        pass

    def _cycle_todo_mode(self) -> None:
        """Cycle through auto → priority → direct → auto."""
        modes = TodoModeLabel._MODES
        current = getattr(self._config, "todo_mode", "auto")
        try:
            idx = modes.index(current)
        except ValueError:
            idx = 0
        next_mode = modes[(idx + 1) % len(modes)]
        self._config.todo_mode = next_mode
        try:
            lbl = self.query_one("#todo-mode-label", TodoModeLabel)
            lbl.update(TodoModeLabel._LABELS[next_mode])
            for m in modes:
                lbl.remove_class(f"todo-{m}")
            lbl.add_class(f"todo-{next_mode}")
        except Exception:
            pass
        # Show verbose description in the message list
        try:
            ml = self.query_one("#message-list", MessageList)
            desc = TodoModeLabel._DESCRIPTIONS.get(next_mode, next_mode)
            ml.add_system_message(desc, style="dim")
        except Exception:
            pass

    def _ctx_thresh_label(self) -> str:
        t = getattr(self._config, "compress_threshold", 10)
        h = getattr(self._config, "hard_limit", 20)
        return f"ctx:{t}/{h}"

    def _cycle_ctx_thresh(self) -> None:
        """Cycle through compression threshold presets."""
        presets = CtxThreshLabel._PRESETS
        current = (getattr(self._config, "compress_threshold", 10),
                   getattr(self._config, "hard_limit", 20))
        # Find current preset index
        idx = 0
        for i, (t, h, _) in enumerate(presets):
            if (t, h) == current:
                idx = i
                break
        next_t, next_h, next_lbl = presets[(idx + 1) % len(presets)]
        self._config.compress_threshold = next_t
        self._config.hard_limit = next_h
        try:
            self.query_one("#ctx-thresh-label", CtxThreshLabel).update(next_lbl)
        except Exception:
            pass
        try:
            ml = self.query_one("#message-list", MessageList)
            ml.add_system_message(
                f"[dim]Context compression: summarize after [bold]{next_t}[/bold] msgs, "
                f"truncate after [bold]{next_h}[/bold] msgs.[/dim]",
                style="",
            )
        except Exception:
            pass

    def _update_mcp_label(self) -> None:
        try:
            statuses = self._mcp_manager.get_status()
            connected = [(n, c, t) for n, c, t in statuses if c]
            label = self.query_one("#mcp-label", Label)
            if connected:
                total_tools = sum(t for _, _, t in connected)
                label.update(f"[mcp: {len(connected)} server(s), {total_tools} tools]")
            else:
                label.update("")
        except Exception:
            pass

    # ── Input handling ────────────────────────────────────────────────────────

    def on_input_submitted(self, event) -> None:
        # Guard: only handle our custom InputSubmitted message.
        # Textual's built-in Input.Submitted (e.g. from DirectoryDialog)
        # has the same handler name but lacks the .text attribute.
        if not hasattr(event, 'text'):
            return
        text = event.text.strip()
        if not text:
            return

        # Slash commands
        if text.startswith("/"):
            self._handle_slash_command(text)
            return

        self._run_query(text)

    def _handle_slash_command(self, text: str) -> None:
        parts = text.split()
        cmd = parts[0].lower()
        args = parts[1:]
        ml = self.query_one("#message-list", MessageList)

        if cmd == "/help":
            self.action_open_help()
        elif cmd == "/clear":
            self.action_clear_screen()
        elif cmd == "/cd":
            self._handle_cd_command(args)
        elif cmd == "/setup":
            self.action_open_setup()
        elif cmd == "/plan":
            self.action_toggle_plan()
        elif cmd == "/logo":
            self._handle_logo_command()
        elif cmd == "/newdaily":
            self.run_worker(self._handle_newdaily_command(), thread=False)
        elif cmd == "/abort":
            self._abort_query()
        elif cmd == "/stop":
            self._stop_query()
        elif cmd == "/resume":
            self._resume_query()
        elif cmd == "/history":
            self._show_history()
        elif cmd == "/exit":
            self.exit()
        elif cmd == "/mcp":
            self.run_worker(self._handle_mcp_command(args), thread=False)
        elif cmd == "/skill":
            self._handle_skill_command(args)
        else:
            ml.add_system_message(f"Unknown command: {cmd}. Type /help for available commands.")

    def _handle_logo_command(self) -> None:
        """Cycle to next logo style (instant, no LLM)."""
        ml = self.query_one("#message-list", MessageList)
        try:
            logo = self.query_one("#logo-panel", LogoPanel)
            style = logo.next_logo_style()
            ml.add_system_message(f"Logo style: {style}", style="dim")
        except Exception as e:
            ml.add_system_message(f"Logo error: {e}", style="red")

    async def _handle_newdaily_command(self) -> None:
        """Regenerate daily.md via LLM. Only one run at a time."""
        ml = self.query_one("#message-list", MessageList)
        from tui.logo_panel import LogoPanel, NewsPanel

        # ── Mutex guard ───────────────────────────────────────────────────────
        if self._newdaily_running:
            ml.add_system_message(
                "● /newdaily is already running — please wait for it to finish.",
                style="yellow",
            )
            return

        self._newdaily_running = True

        # Mark panel as busy (yellow)
        try:
            self.query_one("#logo-panel", LogoPanel).set_daily_status(NewsPanel.STATUS_BUSY)
        except Exception:
            pass

        ml.add_system_message("● Updating daily.md via LLM… (web search for 15-20 headlines may take 2-5 min; "
                              "for faster results use qwen-turbo or qwen-flash in /setup)", style="yellow")

        try:
            from agent.daily import force_update
            # Wrap with asyncio.wait_for so CancelledError / timeout always
            # propagates cleanly and the finally block runs.
            import asyncio as _asyncio
            success, msg = await _asyncio.wait_for(
                force_update(self._config),
                timeout=600,  # 10-minute hard cap (15-20 headlines web search can take 3-5 min)
            )

            if success:
                # Green: success — refresh panels with new content
                try:
                    logo = self.query_one("#logo-panel", LogoPanel)
                    logo.set_daily_status(NewsPanel.STATUS_OK)
                    logo.refresh_daily()
                except Exception:
                    pass
                ml.add_system_message(f"● {msg}", style="green")
            else:
                # Red: LLM failed (fallback written)
                try:
                    self.query_one("#logo-panel", LogoPanel).set_daily_status(NewsPanel.STATUS_STALE)
                except Exception:
                    pass
                ml.add_system_message(f"● {msg}", style="yellow")

        except _asyncio.TimeoutError:
            try:
                self.query_one("#logo-panel", LogoPanel).set_daily_status(NewsPanel.STATUS_STALE)
            except Exception:
                pass
            ml.add_system_message(
                "● /newdaily timed out (10 min) — try a faster model (qwen-turbo / qwen-flash) via /setup.", style="red"
            )
        except BaseException as e:
            # Catches CancelledError, WorkerCancelled, and all other exceptions
            try:
                self.query_one("#logo-panel", LogoPanel).set_daily_status(NewsPanel.STATUS_STALE)
            except Exception:
                pass
            err_name = type(e).__name__
            ml.add_system_message(f"● newdaily error ({err_name}): {e}", style="red")
        finally:
            # MUST always run so the mutex is released
            self._newdaily_running = False

    # ── CD command handler ──────────────────────────────────────────────────

    def _handle_cd_command(self, args: list[str]) -> None:
        """Handle /cd <path> command to change working directory.
        With no args, opens a visual directory picker dialog.
        """
        ml = self.query_one("#message-list", MessageList)
        if not args:
            # Open the visual directory browser
            def _after_pick(chosen: str | None) -> None:
                if chosen:
                    self._apply_cd(ml, chosen)
                else:
                    ml.add_system_message(f"Current directory: {self._cwd}", style="dim")
            self.push_screen(DirectoryDialog(str(self._cwd)), _after_pick)
            return
        raw_path = " ".join(args)
        target_str = os.path.expanduser(raw_path)
        import glob as _glob
        # If it still looks like a partial/glob path, try to resolve the first match
        expanded = _glob.glob(target_str)
        if expanded:
            target_str = expanded[0]
        self._apply_cd(ml, target_str)

    def _apply_cd(self, ml, raw_path: str) -> None:
        """Resolve and apply a new working directory."""
        target = Path(os.path.expanduser(str(raw_path))).resolve()
        if not target.exists():
            ml.add_system_message(f"Directory not found: {target}", style="red")
            return
        if not target.is_dir():
            ml.add_system_message(f"Not a directory: {target}", style="red")
            return
        try:
            os.chdir(target)
            self._cwd = target
            self._config.cwd = str(target)
            self._update_cwd_label()
            ml.add_system_message(f"Working directory: {self._fmt_cwd()}", style="dim")
        except OSError as e:
            ml.add_system_message(f"Cannot change directory: {e}", style="red")


    # ── MCP command handler ──────────────────────────────────────────────────

    async def _sync_mcp_changes(
        self,
        added: set[str],
        removed: set[str],
        new_mcp: dict[str, dict],
        newly_disabled: set[str] | None = None,
        newly_enabled: set[str] | None = None,
    ) -> None:
        """Connect/disconnect servers after /setup save, respecting autoconnect."""
        ml = self.query_one("#message-list", MessageList)
        # Disconnect removed servers
        for name in removed:
            try:
                await self._mcp_manager.disconnect_server(name)
                ml.add_system_message(
                    f"MCP [cyan]{name}[/cyan] [yellow]disconnected[/yellow] (removed from config).",
                    style="dim",
                )
            except Exception as e:
                ml.add_system_message(f"Error disconnecting {name}: {e}", style="red")
        # Disconnect servers whose autoconnect was turned OFF
        for name in (newly_disabled or set()):
            try:
                await self._mcp_manager.disconnect_server(name)
                ml.add_system_message(
                    f"MCP [cyan]{name}[/cyan] [yellow]disconnected[/yellow] (autoconnect disabled).",
                    style="dim",
                )
            except Exception as e:
                ml.add_system_message(f"Error disconnecting {name}: {e}", style="red")
        # Connect newly-added servers (only if autoconnect is enabled)
        for name in added:
            raw = new_mcp.get(name, {})
            if not raw.get("autoconnect", True):
                ml.add_system_message(
                    f"[dim]\u23f8 MCP [cyan]{name}[/cyan] added but autoconnect is off.[/dim]",
                    style="dim",
                )
                continue
            try:
                await self._mcp_manager.connect_server_from_raw(name, raw)
                client = self._mcp_manager._clients.get(name)
                tc = len(client._tools) if client else 0
                ml.add_system_message(
                    f"[green]\u2713[/green] MCP [cyan]{name}[/cyan] connected ({tc} tool(s)).",
                    style="dim",
                )
            except Exception as e:
                ml.add_system_message(
                    f"[red]\u2717[/red] MCP [cyan]{name}[/cyan] failed: {e}", style="red"
                )
        # Connect servers whose autoconnect was turned ON
        for name in (newly_enabled or set()):
            raw = new_mcp.get(name, {})
            try:
                await self._mcp_manager.connect_server_from_raw(name, raw)
                client = self._mcp_manager._clients.get(name)
                tc = len(client._tools) if client else 0
                ml.add_system_message(
                    f"[green]\u2713[/green] MCP [cyan]{name}[/cyan] connected (autoconnect enabled, {tc} tool(s)).",
                    style="dim",
                )
            except Exception as e:
                ml.add_system_message(
                    f"[red]\u2717[/red] MCP [cyan]{name}[/cyan] failed: {e}", style="red"
                )
        self._update_mcp_label()

    async def _connect_mcp_servers(self) -> None:
        """Auto-connect MCP servers that have autoconnect enabled (default: True)."""
        ml = self.query_one("#message-list", MessageList)
        for name, raw in self._config.mcp_servers.items():
            # Respect autoconnect flag; default True for backward-compat
            if not raw.get("autoconnect", True):
                ml.add_system_message(
                    f"[dim]\u23f8 MCP [cyan]{name}[/cyan] skipped (autoconnect off)[/dim]",
                    style="dim",
                )
                continue
            try:
                await self._mcp_manager.connect_server_from_raw(name, raw)
                client = self._mcp_manager._clients.get(name)
                tc = len(client._tools) if client else 0
                ml.add_system_message(
                    f"[green]\u2713[/green] MCP server [cyan]{name}[/cyan] connected "
                    f"({tc} tool(s))",
                    style="dim",
                )
            except Exception as e:
                ml.add_system_message(
                    f"[red]\u2717[/red] MCP server [cyan]{name}[/cyan] failed: {e}",
                    style="red",
                )
        self._update_mcp_label()

    async def _handle_mcp_command(self, args: list[str]) -> None:
        """Handle /mcp list|tools|connect|disconnect|reconnect commands."""
        ml = self.query_one("#message-list", MessageList)
        sub = args[0].lower() if args else "list"

        if sub == "list":
            statuses = self._mcp_manager.get_status()
            if not statuses:
                ml.add_system_message(
                    "No MCP servers connected.\n"
                    "  Add via /setup, config.json, or:\n"
                    "  /mcp connect <name> {\"type\":\"stdio\",\"command\":\"...\"}\n"
                    "  /mcp connect <name> {\"type\":\"sse\",\"url\":\"http://...\"}\n"
                    "Use /mcp tools to list available tools after connecting.",
                    style="dim",
                )
                return
            lines = ["Connected MCP servers (use '/mcp tools' to list all tools):"]
            total_tools = 0
            for name, connected, tool_count in statuses:
                status = "[green]✓ connected[/green]" if connected else "[red]✗ disconnected[/red]"
                lines.append(f"  [cyan]{name}[/cyan]  {status}  [dim]{tool_count} tool(s)[/dim]")
                total_tools += tool_count
            lines.append(f"\n  Total: {len(statuses)} server(s), {total_tools} tool(s) available")
            ml.add_system_message("\n".join(lines), style="dim")

        elif sub == "tools":
            # /mcp tools [server_name]
            # If server_name given: list only that server's tools with full description
            # If not given: list all servers and their tools
            target = args[1] if len(args) >= 2 else None
            statuses = self._mcp_manager.get_status()
            if not statuses:
                ml.add_system_message("No MCP servers connected.", style="dim")
                return

            lines: list[str] = []
            for srv_name, connected, tool_count in statuses:
                if target and srv_name != target:
                    continue
                client = self._mcp_manager._clients.get(srv_name)
                if not client or not connected:
                    lines.append(f"[red]{srv_name}[/red]: disconnected")
                    continue
                tool_defs = client._tools
                lines.append(f"[bold cyan]{srv_name}[/bold cyan] — {tool_count} tool(s):")
                if not tool_defs:
                    lines.append("  (no tools registered)")
                else:
                    for td in tool_defs:
                        tname = td.get("name", "?")
                        desc = td.get("description", "").strip().splitlines()[0] if td.get("description") else "(no description)"
                        # Show input schema required fields if any
                        schema = td.get("inputSchema") or td.get("input_schema") or {}
                        required = schema.get("required", [])
                        props = list(schema.get("properties", {}).keys())
                        params_hint = ""
                        if props:
                            params_hint = " [dim](params: " + ", ".join(
                                f"[bold]{p}[/bold]" if p in required else p
                                for p in props
                            ) + ")[/dim]"
                        lines.append(f"  [green]{srv_name}__{tname}[/green]{params_hint}")
                        lines.append(f"    {desc}")

            if not lines:
                ml.add_system_message(
                    f"No server named {target!r} found. Use '/mcp list' to see connected servers.",
                    style="yellow",
                )
                return
            ml.add_system_message("\n".join(lines), style="dim")

        elif sub == "connect" and len(args) >= 3:
            # /mcp connect <name> <json_config>
            name = args[1]
            raw_json = " ".join(args[2:])
            try:
                raw = json.loads(raw_json)
                await self._mcp_manager.connect_server_from_raw(name, raw)
                # Report how many tools were loaded
                client = self._mcp_manager._clients.get(name)
                tool_count = len(client._tools) if client else 0
                ml.add_system_message(
                    f"MCP server [cyan]{name}[/cyan] connected. "
                    f"[green]{tool_count} tool(s)[/green] available.\n"
                    f"  Use '/mcp tools {name}' to see tool details.",
                    style="green",
                )
                self._update_mcp_label()
            except Exception as e:
                ml.add_system_message(f"Failed to connect {name!r}: {e}", style="red")

        elif sub == "disconnect" and len(args) >= 2:
            name = args[1]
            await self._mcp_manager.disconnect_server(name)
            ml.add_system_message(f"MCP server [yellow]{name}[/yellow] disconnected.", style="dim")
            self._update_mcp_label()

        elif sub == "reconnect":
            # /mcp reconnect [server_name]
            # reconnects one named server, or all servers if no name given
            target = args[1] if len(args) >= 2 else None
            clients_snapshot = dict(self._mcp_manager._clients)
            targets = (
                {target: clients_snapshot[target]}
                if target and target in clients_snapshot
                else clients_snapshot
            )
            if not targets:
                ml.add_system_message(
                    "No servers to reconnect. Use '/mcp connect' first.",
                    style="yellow",
                )
                return
            results: list[str] = []
            for srv_name, client in targets.items():
                cfg = client.config
                try:
                    await self._mcp_manager.connect_server(srv_name, cfg)  # re-registers
                    c2 = self._mcp_manager._clients.get(srv_name)
                    tc = len(c2._tools) if c2 else 0
                    results.append(f"  [cyan]{srv_name}[/cyan] [green]reconnected[/green] ({tc} tools)")
                except Exception as e:
                    results.append(f"  [cyan]{srv_name}[/cyan] [red]failed[/red]: {e}")
            ml.add_system_message("Reconnect results:\n" + "\n".join(results), style="dim")
            self._update_mcp_label()

        else:
            ml.add_system_message(
                "MCP commands:\n"
                "  /mcp list                          — list connected servers\n"
                "  /mcp tools [server]                — list tools (all or one server)\n"
                "  /mcp connect <name> <json>         — connect a new server\n"
                "  /mcp disconnect <name>             — disconnect a server\n"
                "  /mcp reconnect [name]              — reconnect one or all servers\n"
                "\n"
                "Examples:\n"
                "  /mcp connect demo {\"type\":\"stdio\",\"command\":\"python\",\"args\":[\"server.py\"]}\n"
                "  /mcp connect demo {\"type\":\"sse\",\"url\":\"http://localhost:8765/sse\"}\n"
                "  /mcp tools demo",
                style="dim",
            )

    # ── Skill command handler ─────────────────────────────────────────────────

    def _handle_skill_command(self, args: list[str]) -> None:
        """Handle /skill <name> [args...] command."""
        ml = self.query_one("#message-list", MessageList)

        if not args:
            # List available skills
            skills = self._skill_loader.load_all(force_reload=True)
            if not skills:
                ml.add_system_message(
                    f"No skills found. Place .md files in: {self._skill_loader.skills_dir}",
                    style="dim",
                )
                return
            lines = ["Available skills:"]
            for s in skills:
                hint = f" {s.argument_hint}" if s.argument_hint else ""
                lines.append(f"  [cyan]{s.name}[/cyan]{hint}  —  {s.description}")
            ml.add_system_message("\n".join(lines), style="dim")
            return

        skill_name = args[0]
        skill_args = " ".join(args[1:]) if len(args) > 1 else ""
        skill = self._skill_loader.find_skill(skill_name)

        if skill is None:
            ml.add_system_message(
                f"Skill [yellow]{skill_name!r}[/yellow] not found. Use /skill to list available skills.",
                style="yellow",
            )
            return

        # Use skill content as system prompt prefix
        system_prefix = skill.content
        prompt = skill_args or f"Run skill: {skill_name}"
        ml.add_system_message(
            f"Running skill [cyan]{skill_name}[/cyan]...",
            style="dim",
        )
        self._run_query(prompt, system_prefix=system_prefix)

    # ── Query execution ───────────────────────────────────────────────────────

    def _run_query(self, text: str, system_prefix: str = "") -> None:
        if not self._config.is_configured():
            ml = self.query_one("#message-list", MessageList)
            ml.add_system_message("Please configure your API key first (Ctrl+S or /setup).", style="yellow")
            return

        ml = self.query_one("#message-list", MessageList)
        input_bar = self.query_one("#input-bar", InputBar)

        # Show user message
        ml.add_user_message(text)
        ml.show_thinking()
        input_bar.set_busy(True)

        # Add to message history
        user_msg = UserMessage(content=text)
        self._messages.append(user_msg)

        # Run the async query on the app's event loop
        self.run_worker(self._run_query_async(text, system_prefix), exclusive=True, thread=False)

    async def _run_query_async(self, text: str, system_prefix: str = "") -> None:
        ml = self.query_one("#message-list", MessageList)
        input_bar = self.query_one("#input-bar", InputBar)

        # Build engine fresh each time in case config / MCP changed
        engine = self._build_engine()
        # Inject current working directory into system prompt
        base_prompt = _SYSTEM_PROMPT.format(cwd=self._cwd)
        # Inject TodoWrite behaviour hint based on todo_mode
        todo_mode = getattr(self._config, "todo_mode", "auto")
        todo_hint = _TODO_MODE_PROMPTS.get(todo_mode, "")
        if todo_hint:
            base_prompt = base_prompt.rstrip() + "\n\n" + todo_hint + "\n"
        system_prompt = (system_prefix + "\n\n" + base_prompt) if system_prefix else base_prompt

        try:
            # Hide thinking before first turn
            ml.hide_thinking()

            # Track current bubble across turns.
            # Bubble is created LAZILY on first text chunk so that tool cards
            # (which arrive before text in tool-call rounds) mount ABOVE the bubble.
            _current_bubble: list = [None]   # mutable cell
            _turn_has_text:  list = [False]  # did this turn produce any text?

            def on_turn_start() -> None:
                """New LLM generation round: reset per-turn state. Don't create bubble yet."""
                _current_bubble[0] = None
                _turn_has_text[0] = False

            def _ensure_bubble() -> "AssistantBubble":
                """Lazily create the bubble the first time text arrives."""
                if _current_bubble[0] is None:
                    bubble = ml.begin_assistant_message()
                    _current_bubble[0] = bubble
                return _current_bubble[0]

            def on_turn_end(has_tools: bool) -> None:
                """Round finished: render final Markdown if we have a bubble."""
                bubble = _current_bubble[0]
                if bubble is not None:
                    try:
                        bubble.finish()
                    except Exception:
                        pass
                ml.finish_assistant_message()
                _current_bubble[0] = None
                _turn_has_text[0] = False

            def on_text(chunk: str) -> None:
                _turn_has_text[0] = True
                _ensure_bubble()
                ml.append_text_chunk(chunk)

            def on_tool_use(name: str, tool_id: str, tool_input: dict) -> None:
                # Tool cards mount here — before any bubble for this turn
                ml.add_tool_call(name, tool_id, tool_input)

            def on_tool_result(tool_id: str, result: str, is_error: bool) -> None:
                ml.set_tool_result(tool_id, result, is_error)

            def on_context_update(turns: int, est_tokens: int, was_compressed: bool) -> None:
                """Update context-label in the status bar (numbers only, no chat banners)."""
                label_text = f"ctx: {turns} msgs ~{est_tokens//1000}k tok"
                try:
                    self.query_one("#context-label", Label).update(label_text)
                except Exception:
                    pass

            def on_compression_done() -> None:
                """Called when the background compression task finishes successfully."""
                ml.add_system_message(
                    "💾 Memory compression complete — past conversations have been summarized.",
                    style="dim",
                )

            def on_compression_wait(waiting: bool) -> None:
                """Show/hide a TUI indicator while background compression is awaited."""
                try:
                    lbl = self.query_one("#context-label", Label)
                    if waiting:
                        lbl.update("ctx: ⏳ compressing...")
                        ml.add_system_message(
                            "⏳ Background memory compression is still running — "
                            "waiting for it to finish before your next message...",
                            style="dim",
                        )
                    # Label will be refreshed by the next on_context_update call
                except Exception:
                    pass

            async def on_iteration_limit(iteration: int) -> bool:
                """
                Called when the 30-round limit is reached in allow_all mode.
                Shows an inline confirmation card and waits for the user to decide.
                Returns True to continue up to 100 rounds, False to stop.
                """
                import asyncio as _asyncio
                future: _asyncio.Future = _asyncio.get_event_loop().create_future()
                ml.add_system_message(
                    f"⚠ Agent has run [bold]{iteration}[/bold] tool-call rounds (normal limit is 30).\n"
                    f"Permission mode is [bold red]Allow All[/bold red] — you may continue up to 100 rounds.\n"
                    f"Please review the tool calls above and decide whether to continue.",
                    style="yellow",
                )
                from tui.views import PermissionCard as _PermCard
                # Reuse PermissionCard: Allow Once = continue, Deny = stop
                try:
                    card = ml.add_permission_card(
                        "IterationLimit",
                        f"Reached {iteration} rounds. Continue executing tools?",
                        future,
                    )
                except Exception:
                    return False
                result = await future
                from agent.tools.base import PermissionResult
                return result in (PermissionResult.ALLOW_ONCE, PermissionResult.ALLOW_ALL)

            updated = await engine.stream_query(
                messages=self._messages,
                system_prompt=system_prompt,
                on_text=on_text,
                on_tool_use=on_tool_use,
                on_tool_result=on_tool_result,
                confirm_fn=self._make_confirm_fn(),
                on_context_update=on_context_update,
                on_turn_start=on_turn_start,
                on_turn_end=on_turn_end,
                on_iteration_limit=on_iteration_limit,
                on_compression_wait=on_compression_wait,
                on_compression_done=on_compression_done,
            )
            self._messages = updated
            # Final bubble cleanup (in case last turn ended without on_turn_end)
            ml.finish_assistant_message()
            input_bar.set_busy(False)
            input_bar.focus_input()
            self._save_session()
            # Async: update user habits in the background (fire-and-forget)
            self.run_worker(
                self._update_memory_async(updated),
                thread=False,
                exclusive=False,
            )

        except Exception as e:
            ml.hide_thinking()
            ml.add_system_message(f"Error: {e}", style="red")
            input_bar.set_busy(False)
            input_bar.focus_input()

    def _make_confirm_fn(self):
        """Build the permission callback respecting current permission_mode."""
        app = self

        async def confirm_fn(tool_name: str, description: str, params: dict) -> str:
            mode = app._config.permission_mode

            # deny_all: never execute
            if mode == "deny_all":
                return PermissionResult.DENY

            # allow_all: execute everything without asking
            if mode == "allow_all":
                return PermissionResult.ALLOW_ONCE

            # allow_safe: safe tools auto-approved, destructive ones must ask
            if mode == "allow_safe":
                if tool_name in SAFE_TOOLS:
                    return PermissionResult.ALLOW_ONCE
                # Fall through to inline ask for unsafe tools

            # ask_always (or allow_safe with an unsafe tool): show inline card
            import asyncio as _asyncio
            future: _asyncio.Future = _asyncio.get_event_loop().create_future()

            # Mount inline card in message list (same asyncio loop, direct call OK)
            try:
                ml = app.query_one("#message-list", MessageList)
                brief = description[:120] if description else str(params)[:120]
                ml.add_permission_card(tool_name, brief, future)
            except Exception:
                return PermissionResult.DENY

            # Wait for user to click a button
            result = await future
            return result if result else PermissionResult.DENY

        return confirm_fn

    def _abort_query(self) -> None:
        # Cancel any running workers
        self.workers.cancel_all()
        ml = self.query_one("#message-list", MessageList)
        input_bar = self.query_one("#input-bar", InputBar)
        ml.hide_thinking()
        ml.add_system_message("Request aborted.", style="yellow")
        input_bar.set_busy(False)

    def _stop_query(self) -> None:
        """
        Stop the current run and save a resume point.
        Snapshots the FULL message history so /resume can restore the exact
        execution context (including all tool calls already completed).
        """
        ml = self.query_one("#message-list", MessageList)
        input_bar = self.query_one("#input-bar", InputBar)

        # Find the last user text for display purposes only
        original_query: str = ""
        for msg in reversed(self._messages):
            if not hasattr(msg, "to_api_format"):
                continue
            api = msg.to_api_format()
            if api.get("role") == "user":
                content = api.get("content", "")
                if isinstance(content, str):
                    original_query = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            original_query = block.get("text", "")
                            break
                if original_query:
                    break

        # Cancel all workers (stops LLM streaming)
        self.workers.cancel_all()
        ml.hide_thinking()
        input_bar.set_busy(False)

        # Save a deep snapshot of the message history at this exact moment
        import copy
        self._stopped_at = {
            "messages": copy.deepcopy(self._messages),
            "original_query": original_query,
        }

        short = original_query[:80] + ("..." if len(original_query) > 80 else "")
        completed = sum(
            1 for m in self._messages
            if hasattr(m, "to_api_format") and m.to_api_format().get("role") == "assistant"
        )
        ml.add_system_message(
            f"Stopped after {completed} assistant turn(s).\n"
            f"Resume point: \"{short}\"\n"
            "Type [bold]/resume[/bold] to continue from this exact point.",
            style="yellow",
        )

    def _resume_query(self) -> None:
        """
        Resume from the last /stop breakpoint.
        Restores the full message history snapshot captured at /stop time,
        then sends a continuation prompt so the LLM can pick up where it left off.
        """
        ml = self.query_one("#message-list", MessageList)

        if not self._stopped_at:
            ml.add_system_message(
                "No resume point available. Use /stop during a run first.",
                style="yellow",
            )
            return

        snapshot = self._stopped_at
        self._stopped_at = None  # Clear after use

        # Restore the exact message history from the snapshot
        self._messages = snapshot["messages"]
        original_query = snapshot["original_query"]

        short = original_query[:80] + ("..." if len(original_query) > 80 else "")
        ml.add_system_message(
            f"Resuming from breakpoint: \"{short}\"\n"
            f"Context restored ({len(self._messages)} messages). Continuing...",
            style="cyan",
        )

        # The continuation message tells the LLM exactly what happened and what to do next
        continuation = (
            "[Resuming interrupted task]\n"
            "You were previously working on the task above and were interrupted mid-execution. "
            "The conversation history above shows everything you had already completed. "
            "Please review what has already been done and continue from where you left off, "
            "completing any remaining steps without repeating work already finished."
        )
        system_prefix = (
            "The user interrupted this task mid-execution and is now resuming. "
            "Review the full conversation history to understand what has already been done, "
            "then continue completing the remaining work."
        )
        self._run_query(continuation, system_prefix=system_prefix)

    # ── Plan Mode callbacks ───────────────────────────────────────────────────

    def _on_plan_update(self, items, merge: bool) -> None:
        """Called by PlanTool when AI updates the task list."""
        def _update():
            plan = self.query_one("#plan-panel", PlanPanel)
            plan.update_todos(items, merge)
            if not plan.visible:
                plan.visible = True
        self.call_from_thread(_update)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_open_setup(self) -> None:
        import copy
        # Build current MCP status map to inject into dialog
        mcp_statuses = {
            name: connected
            for name, connected, _ in self._mcp_manager.get_status()
        }
        # Deep-copy so mutations inside the dialog don't affect old_mcp comparison
        old_mcp = copy.deepcopy(self._config.mcp_servers)

        dialog = SetupDialog(self._config, mcp_manager=self._mcp_manager)
        dialog.set_mcp_status(mcp_statuses)

        def _after_setup(result: AgentConfig | None) -> None:
            if result:
                self._config = result
                self._update_status()
                ml = self.query_one("#message-list", MessageList)
                ml.add_system_message(f"Settings saved. Model: {result.model}", style="green")
                # Sync MCP server changes
                new_mcp = result.mcp_servers
                removed = set(old_mcp) - set(new_mcp)
                added   = set(new_mcp) - set(old_mcp)
                # Detect existing servers whose autoconnect flag changed
                stayed = set(old_mcp) & set(new_mcp)
                newly_disabled = {
                    n for n in stayed
                    if old_mcp[n].get("autoconnect", True) and not new_mcp[n].get("autoconnect", True)
                }
                newly_enabled = {
                    n for n in stayed
                    if not old_mcp[n].get("autoconnect", True) and new_mcp[n].get("autoconnect", True)
                }
                if removed or added or newly_disabled or newly_enabled:
                    self.run_worker(
                        self._sync_mcp_changes(added, removed, new_mcp, newly_disabled, newly_enabled),
                        thread=False,
                    )

        self.push_screen(dialog, _after_setup)

    def action_open_help(self) -> None:
        self.push_screen(HelpDialog())

    def action_toggle_plan(self) -> None:
        panel = self.query_one("#plan-panel", PlanPanel)
        panel.toggle()
        # Update the toggle button text to reflect open/closed state
        try:
            is_visible = panel.styles.display != "none"
            btn_text = "[Plan ▼]" if is_visible else "[Plan ▶]"
            self.query_one("#plan-toggle-label", PlanToggleLabel).update(btn_text)
        except Exception:
            pass

    def action_clear_screen(self) -> None:
        self._messages.clear()
        self.query_one("#message-list", MessageList).clear_messages()
        self.query_one("#message-list", MessageList).add_system_message("Conversation cleared.", style="dim")

    def action_toggle_theme(self) -> None:
        if self.app.dark:
            self.app.dark = False
            self._config.theme = "light"
        else:
            self.app.dark = True
            self._config.theme = "dark"
        save_config(self._config)

    # ── Session persistence ───────────────────────────────────────────────────

    def _save_session(self) -> None:
        try:
            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            session_file = SESSION_DIR / f"{self._session_id}.json"
            data = {
                "session_id": self._session_id,
                "model": self._config.model,
                "messages": messages_to_api(self._messages),
                "updated_at": datetime.now().isoformat(),
            }
            session_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def _update_memory_async(self, messages: list) -> None:
        """Background task: update user_habits.md AND user_info.md via LLM after each session turn."""
        try:
            # Run both updates concurrently
            await asyncio.gather(
                self._memory.update_habits(messages),
                self._memory.update_info(messages),
                return_exceptions=True,
            )
        except Exception:
            pass

    def _show_history(self) -> None:
        ml = self.query_one("#message-list", MessageList)
        try:
            sessions = sorted(SESSION_DIR.glob("*.json"), reverse=True)[:10]
            if not sessions:
                ml.add_system_message("No session history found.", style="dim")
                return
            lines = ["Recent sessions:"]
            for s in sessions:
                try:
                    data = json.loads(s.read_text(encoding="utf-8"))
                    lines.append(f"  {s.stem}  model={data.get('model', '?')}  msgs={len(data.get('messages', []))}")
                except Exception:
                    lines.append(f"  {s.stem}")
            ml.add_system_message("\n".join(lines), style="dim")
        except Exception as e:
            ml.add_system_message(f"Error loading history: {e}", style="red")
