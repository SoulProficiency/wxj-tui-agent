"""
InputBar: Multi-line input area with slash-command auto-completion.
- Enter to submit, Shift+Enter for newline
- Tab to cycle through slash-command completions
- Up/Down to scroll through input history (like a shell)
- Ctrl+C to interrupt current request
"""
from __future__ import annotations

import os
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, TextArea, Static


# ── Slash commands registry ───────────────────────────────────────────────────

SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help",    "Show help and available commands"),
    ("/clear",   "Clear conversation history"),
    ("/cd",      "Change working directory: /cd <path>"),
    ("/setup",   "Configure API key, model, and settings"),
    ("/plan",    "Toggle Plan Mode (task list panel)"),
    ("/skill",   "Run a skill: /skill <name> [args]"),
    ("/mcp",     "Manage MCP servers: /mcp list|connect|disconnect"),
    ("/history", "Show session history"),
    ("/exit",    "Exit the application"),
    ("/abort",   "Abort the current request"),
    ("/stop",    "Stop current run and save a resume point"),
    ("/resume",  "Resume from the last stop point"),
    ("/logo",      "Cycle logo style (instant, theme-aware)"),
    ("/newdaily",   "Regenerate daily.md via LLM (news + greeting)"),
]

SLASH_NAMES = [cmd for cmd, _ in SLASH_COMMANDS]

_MAX_HISTORY = 200  # maximum entries kept in input history


# ── Messages (Textual message bus) ────────────────────────────────────────────

class InputSubmitted(Message):
    """Posted when the user submits input."""
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class SlashCommandSelected(Message):
    """Posted when a slash command is chosen from completions."""
    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


# ── Completion popup ──────────────────────────────────────────────────────────

class CompletionList(Widget):
    """Popup list of matching slash command completions — floats ABOVE the input bar.

    Mount this widget into the chat-area container (NOT inside InputBar),
    so it can use dock:bottom + margin-bottom to sit just above the InputBar.
    """

    DEFAULT_CSS = """
    CompletionList {
        background: $surface;
        border: solid $accent;
        height: auto;
        max-height: 12;
        width: 60;
        display: none;
        layer: overlay;
        dock: bottom;
        margin-bottom: 3;
        margin-left: 2;
    }
    CompletionList .completion-item {
        padding: 0 1;
        height: 1;
    }
    CompletionList .completion-item:hover {
        background: $accent;
        color: $background;
    }
    CompletionList .completion-selected {
        background: $accent;
        color: $background;
    }
    CompletionList .completion-desc {
        color: $text-muted;
        padding-left: 2;
    }
    """

    items: reactive[list[tuple[str, str]]] = reactive([], layout=True)
    selected_index: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield Vertical(id="completion-items")

    def watch_items(self, new_items: list[tuple[str, str]]) -> None:
        self.styles.display = "block" if new_items else "none"
        self.selected_index = 0
        self._rebuild()

    def watch_selected_index(self, _: int) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        try:
            container = self.query_one("#completion-items", Vertical)
            container.remove_children()
            for i, (cmd, desc) in enumerate(self.items):
                css = "completion-selected" if i == self.selected_index else "completion-item"
                container.mount(
                    Horizontal(
                        Label(cmd, classes=css),
                        Label(f"  {desc}", classes="completion-desc"),
                    )
                )
        except Exception:
            pass

    def move_selection(self, delta: int) -> None:
        if not self.items:
            return
        self.selected_index = (self.selected_index + delta) % len(self.items)

    def get_selected(self) -> str | None:
        if not self.items:
            return None
        return self.items[self.selected_index][0]

    def hide(self) -> None:
        self.items = []


# ── Custom TextArea that intercepts Enter/Shift+Enter ────────────────────────

class _ChatTextArea(TextArea):
    """
    TextArea subclass:
    - Enter → post SubmitRequest to parent InputBar
    - Shift+Enter → insert newline
    - Tab → pass to parent InputBar for completion
    - Up on first line / Down on last line → HistoryUp/DownRequest for history nav
    """

    class SubmitRequest(Message):
        """Posted when the user presses Enter (no modifiers)."""

    class TabRequest(Message):
        """Posted when Tab is pressed."""

    class HistoryUpRequest(Message):
        """Posted when Up is pressed while cursor is on the first line."""

    class HistoryDownRequest(Message):
        """Posted when Down is pressed while cursor is on the last line."""

    class CompletionUpRequest(Message):
        """Posted when Up is pressed and completion list is open."""

    class CompletionDownRequest(Message):
        """Posted when Down is pressed and completion list is open."""

    # Set by InputBar so this widget knows whether completions are visible
    completion_open: bool = False

    def _on_key(self, event) -> None:
        key = event.key
        if key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.SubmitRequest())
        elif key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")
        elif key == "tab":
            event.prevent_default()
            event.stop()
            self.post_message(self.TabRequest())
        elif key == "up":
            if self.completion_open:
                # Completions visible — route to completion navigation
                event.prevent_default()
                event.stop()
                self.post_message(self.CompletionUpRequest())
            elif self.cursor_location[0] == 0:
                event.prevent_default()
                event.stop()
                self.post_message(self.HistoryUpRequest())
        elif key == "down":
            if self.completion_open:
                event.prevent_default()
                event.stop()
                self.post_message(self.CompletionDownRequest())
            else:
                lines = self.text.splitlines()
                last_line = max(0, len(lines) - 1)
                if self.cursor_location[0] >= last_line:
                    event.prevent_default()
                    event.stop()
                    self.post_message(self.HistoryDownRequest())


# ── Input bar ─────────────────────────────────────────────────────────────────

class InputBar(Widget):
    """
    Bottom input widget.
    Posts InputSubmitted when user presses Enter (without Shift).
    Shows slash-command completions while typing '/'.
    """

    DEFAULT_CSS = """
    InputBar {
        height: auto;
        max-height: 8;
        min-height: 3;
        border-top: solid $accent;
        background: $surface;
        padding: 0 1;
    }
    InputBar #input-label {
        color: $accent;
        text-style: bold;
        height: 1;
    }
    InputBar _ChatTextArea {
        height: auto;
        min-height: 1;
        max-height: 5;
        background: $surface;
        border: none;
        padding: 0;
    }
    InputBar #hint-label {
        color: $text-muted;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "abort_request", "Abort", show=True),
    ]

    is_busy: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._completions = CompletionList(id="completion-popup")
        # Flag: we are programmatically writing to the textarea,
        # so TextArea.Changed should NOT trigger completion updates.
        self._writing = False
        # ── Input history (shell-style) ───────────────────────────────────────
        self._history: list[str] = []   # oldest → newest
        self._hist_idx: int = -1         # -1 = "not browsing"; 0..N-1 = history
        self._hist_draft: str = ""       # preserves current draft when browsing up

    def compose(self) -> ComposeResult:
        yield Label("> ", id="input-label")
        yield _ChatTextArea(id="input-area")
        yield Label("Enter: send  Shift+Enter: newline  Tab: complete  ↑↓: history  Ctrl+S: settings  F1: help  F3/Ctrl+K: plan  Ctrl+C: abort", id="hint-label")
        # NOTE: CompletionList is NOT yielded here — it is mounted into the
        # parent chat-area in on_mount so it can float above the InputBar.

    def on_mount(self) -> None:
        self.query_one("#input-area", _ChatTextArea).focus()
        # Mount the completion popup into the parent container so it appears
        # above InputBar rather than inside it.
        try:
            parent = self.parent
            if parent is not None:
                parent.mount(self._completions)
        except Exception:
            pass

    # ── Helpers ─────────────────────────────────────────────────────

    def _set_textarea(self, text: str) -> None:
        """Write text into the textarea without triggering completion updates."""
        self._writing = True
        try:
            ta = self.query_one("#input-area", _ChatTextArea)
            ta.clear()
            if text:
                ta.insert(text)
        finally:
            # Use call_after_refresh so the Changed events fire BEFORE we
            # clear the flag — this is the key fix.
            self.call_after_refresh(self._clear_writing_flag)

    def _clear_writing_flag(self) -> None:
        self._writing = False

    # ── Event handlers from _ChatTextArea ──────────────────────────────────

    def on__chat_text_area_submit_request(self, event: _ChatTextArea.SubmitRequest) -> None:
        """Enter: if completion list visible → select & submit highlighted item;
        otherwise submit textarea content directly."""
        event.stop()
        if self._completions.items:
            selected = self._completions.get_selected()
            if selected:
                self._hide_completions()
                # Record slash command in history
                self.push_history(selected)
                # Submit the selected command directly
                self._writing = True
                self.call_after_refresh(self._clear_writing_flag)
                self.post_message(InputSubmitted(selected))
                self.query_one("#input-area", _ChatTextArea).clear()
                return
        self._hide_completions()
        self._submit()

    def on__chat_text_area_tab_request(self, event: _ChatTextArea.TabRequest) -> None:
        """Tab: open completion list, or cycle highlight through items.
        Special case: after '/cd ' complete filesystem paths.
        """
        event.stop()
        ta = self.query_one("#input-area", _ChatTextArea)
        current = ta.text

        # — Filesystem path completion for /cd —
        if current.lower().startswith("/cd "):
            partial = current[4:]  # everything after '/cd '
            matches = self._fs_completions(partial)
            if matches:
                # If only one match, fill it in directly
                if len(matches) == 1:
                    self._completions.hide()
                    self._set_textarea(f"/cd {matches[0]}")
                else:
                    # Show as a completion popup (reuse CompletionList)
                    self._completions.items = [(m, "") for m in matches]
            return

        if not self._completions.items:
            # Open the list
            if current.startswith("/"):
                self._update_completions(current)
            return

        # List already open — just move highlight, don't fill/submit
        self._completions.move_selection(1)

    @staticmethod
    def _fs_completions(partial: str) -> list[str]:
        """Return directory completions for the given partial path."""
        partial = os.path.expanduser(partial)
        if not partial:
            base = Path.cwd()
            prefix = ""
        else:
            p = Path(partial)
            if partial.endswith((os.sep, "/")):
                base = p
                prefix = partial
            else:
                base = p.parent
                prefix = partial
        try:
            entries = [
                str(d) + os.sep
                for d in sorted(base.iterdir())
                if d.is_dir() and not d.name.startswith(".")
                and str(d).startswith(prefix.rstrip(os.sep + "/"))
            ]
            return entries[:12]  # cap at 12 to avoid huge lists
        except (PermissionError, FileNotFoundError, OSError):
            return []

    def on_key(self, event) -> None:
        """Escape hides the completion list and resets history browsing."""
        if event.key == "escape":
            self._hide_completions()
            # If browsing history, restore draft and exit history mode
            if self._hist_idx != -1:
                self._hist_idx = -1
                self._set_textarea(self._hist_draft)
                self._hist_draft = ""

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Keep completion list in sync; reset history index when user edits."""
        if self._writing:
            return
        # Any manual edit exits history-browse mode without losing the draft
        self._hist_idx = -1
        text = event.text_area.text
        if text.startswith("/"):
            self._update_completions(text)
        else:
            self._hide_completions()

    # ── Completion Up/Down handlers (when list is open) ───────────────────────

    def on__chat_text_area_completion_up_request(
        self, event: _ChatTextArea.CompletionUpRequest
    ) -> None:
        """Up while completions visible — move selection upward."""
        event.stop()
        self._completions.move_selection(-1)

    def on__chat_text_area_completion_down_request(
        self, event: _ChatTextArea.CompletionDownRequest
    ) -> None:
        """Down while completions visible — move selection downward."""
        event.stop()
        self._completions.move_selection(1)

    # ── History navigation handlers ──────────────────────────────────────────

    def on__chat_text_area_history_up_request(
        self, event: _ChatTextArea.HistoryUpRequest
    ) -> None:
        """Up on first line: go back in history (older)."""
        event.stop()
        if not self._history:
            return
        ta = self.query_one("#input-area", _ChatTextArea)
        # First time pressing Up: save the current draft
        if self._hist_idx == -1:
            self._hist_draft = ta.text
            self._hist_idx = len(self._history) - 1
        elif self._hist_idx > 0:
            self._hist_idx -= 1
        # else already at oldest, stay put
        self._set_textarea(self._history[self._hist_idx])

    def on__chat_text_area_history_down_request(
        self, event: _ChatTextArea.HistoryDownRequest
    ) -> None:
        """Down on last line: go forward in history (newer), then restore draft."""
        event.stop()
        if self._hist_idx == -1:
            return  # not browsing
        if self._hist_idx < len(self._history) - 1:
            self._hist_idx += 1
            self._set_textarea(self._history[self._hist_idx])
        else:
            # Past the newest entry → restore draft
            self._hist_idx = -1
            self._set_textarea(self._hist_draft)
            self._hist_draft = ""

    def push_history(self, text: str) -> None:
        """Record a submitted entry. Deduplicates consecutive identical entries."""
        text = text.strip()
        if not text:
            return
        if self._history and self._history[-1] == text:
            return  # skip duplicate
        self._history.append(text)
        if len(self._history) > _MAX_HISTORY:
            self._history.pop(0)
        # Reset browsing state after submit
        self._hist_idx = -1
        self._hist_draft = ""

    def _update_completions(self, text: str) -> None:
        query = text.strip().lower()
        matches = [(cmd, desc) for cmd, desc in SLASH_COMMANDS if cmd.startswith(query)]
        self._completions.items = matches
        # Sync completion_open flag so _ChatTextArea knows
        try:
            self.query_one("#input-area", _ChatTextArea).completion_open = bool(matches)
        except Exception:
            pass

    def _hide_completions(self) -> None:
        """Hide completion list and clear the completion_open flag."""
        self._completions.hide()
        try:
            self.query_one("#input-area", _ChatTextArea).completion_open = False
        except Exception:
            pass

    def _submit(self) -> None:
        if self.is_busy:
            return
        ta = self.query_one("#input-area", _ChatTextArea)
        text = ta.text.strip()
        if not text:
            return
        # Record in history before clearing
        self.push_history(text)
        # Clear without triggering completions, then post
        self._set_textarea("")
        self.post_message(InputSubmitted(text))

    def action_abort_request(self) -> None:
        self.post_message(InputSubmitted("/abort"))

    def set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        try:
            label = self.query_one("#input-label", Label)
            if busy:
                label.update("[yellow]◐[/yellow] ")
            else:
                label.update("> ")
        except Exception:
            pass

    def focus_input(self) -> None:
        try:
            self.query_one("#input-area", _ChatTextArea).focus()
        except Exception:
            pass
