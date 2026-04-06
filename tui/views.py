"""
TUI Views: Message list, message bubbles, tool call cards.
Uses Textual widgets for rendering.
"""
from __future__ import annotations

import asyncio
import json
from typing import ClassVar

from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical, Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, Collapsible, Static, LoadingIndicator, TextArea

from agent.messages import AssistantMessage, TodoItem, UserMessage


# ── Selectable read-only text area ────────────────────────────────────────────

class _SelectableText(TextArea):
    """
    A read-only TextArea used for message content.
    Supports mouse selection and Ctrl+C copy.
    Height is set dynamically to match content line count.
    """
    DEFAULT_CSS = """
    _SelectableText {
        height: 1;        /* overridden dynamically after load */
        min-height: 1;
        background: transparent;
        border: none;
        padding: 0;
        color: $text;
    }
    _SelectableText:focus {
        border: none;
    }
    """

    def __init__(self, text: str = "", **kwargs) -> None:
        super().__init__(text, read_only=True, show_line_numbers=False, **kwargs)
        if text:
            self._set_height_to_content(text)

    def _set_height_to_content(self, text: str) -> None:
        """Resize widget height to match number of lines in text."""
        lines = max(1, text.count("\n") + 1) if text else 1
        self.styles.height = lines

    def load_text(self, text: str) -> None:  # type: ignore[override]
        """Load text and resize height automatically."""
        super().load_text(text)
        self._set_height_to_content(text)

    def _on_key(self, event) -> None:
        """Allow only copy-related keys; block everything else."""
        if event.key not in ("ctrl+c", "ctrl+a", "shift+left", "shift+right",
                              "shift+up", "shift+down", "shift+home", "shift+end",
                              "left", "right", "up", "down", "home", "end",
                              "pageup", "pagedown"):
            event.prevent_default()
            event.stop()


# ──────────────────────────────────────────────────────────────────────────────
# Individual message widgets
# ──────────────────────────────────────────────────────────────────────────────

class UserBubble(Static):
    """Renders a user message bubble."""

    DEFAULT_CSS = """
    UserBubble {
        margin: 1 0;
        padding: 0 2;
        color: $text;
        background: $surface;
        border-left: thick $accent;
        max-width: 90%;
        align-horizontal: right;
        height: auto;
    }
    UserBubble .bubble-header {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    def __init__(self, content: str, **kwargs):
        super().__init__(**kwargs)
        self._content = content

    def compose(self) -> ComposeResult:
        yield Label("You", classes="bubble-header")
        yield Static(self._content, classes="bubble-text")


class AssistantBubble(Widget):
    """Renders an assistant message. Height auto-grows with streaming content."""

    DEFAULT_CSS = """
    AssistantBubble {
        margin: 1 0;
        padding: 0 2;
        border-left: thick $success;
        max-width: 100%;
        height: auto;
    }
    AssistantBubble .bubble-header {
        color: $success;
        text-style: bold;
    }
    AssistantBubble .assistant-text {
        color: $text;
        height: auto;
        padding: 0;
    }
    """

    def __init__(self, initial_text: str = "", **kwargs):
        super().__init__(**kwargs)
        self._text = initial_text

    @property
    def text(self) -> str:
        return self._text

    def compose(self) -> ComposeResult:
        yield Label("Assistant", classes="bubble-header")
        yield Static("", id="assistant-text", classes="assistant-text")

    def on_mount(self) -> None:
        if self._text:
            self._refresh_display()

    def _refresh_display(self, final: bool = False) -> None:
        """Update the Static widget. During streaming shows plain text; on finish renders Markdown."""
        try:
            st = self.query_one("#assistant-text", Static)
            if final:
                st.update(RichMarkdown(self._text))
            else:
                # Plain text during streaming for performance; Markdown on finish
                st.update(self._text)
        except Exception:
            pass

    def finish(self) -> None:
        """Called when streaming ends to render final Markdown."""
        self._refresh_display(final=True)

    def append_text(self, chunk: str) -> None:
        self._text += chunk
        self._refresh_display()


class PermissionCard(Widget):
    """
    Inline permission confirmation card shown in the message stream.
    Replaces the modal PermissionDialog.
    Resolves an asyncio.Future with a PermissionResult constant.
    """

    DEFAULT_CSS = """
    PermissionCard {
        margin: 1 0 0 2;
        border: round $warning;
        padding: 0 1 1 1;
        background: $surface;
    }
    PermissionCard #perm-header {
        color: $warning;
        text-style: bold;
    }
    PermissionCard #perm-tool {
        color: $accent;
        text-style: bold;
    }
    PermissionCard #perm-desc {
        color: $text;
        margin-top: 1;
    }
    PermissionCard #perm-btn-row {
        height: 3;
        margin-top: 1;
    }
    PermissionCard Button {
        min-width: 14;
        margin-right: 1;
    }
    PermissionCard #perm-answered {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }
    """

    def __init__(
        self,
        tool_name: str,
        description: str,
        future: asyncio.Future,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._description = description
        self._future = future
        self._answered = False

    def compose(self) -> ComposeResult:
        yield Label("  Permission Required", id="perm-header")
        yield Label(f"Tool: {self._tool_name}", id="perm-tool")
        yield Label(self._description[:200], id="perm-desc")
        with Horizontal(id="perm-btn-row"):
            yield Button("Allow Once [Y]", id="perm-allow-once", variant="success")
            yield Button("Allow All  [A]", id="perm-allow-all",  variant="primary")
            yield Button("Deny       [N]", id="perm-deny",       variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        from agent.tools.base import PermissionResult
        if self._answered:
            return
        mapping = {
            "perm-allow-once": PermissionResult.ALLOW_ONCE,
            "perm-allow-all":  PermissionResult.ALLOW_ALL,
            "perm-deny":       PermissionResult.DENY,
        }
        result = mapping.get(event.button.id)
        if result is None:
            return
        self._answered = True
        # Replace buttons with a text label so the card shrinks
        try:
            self.query_one("#perm-btn-row").remove()
        except Exception:
            pass
        labels = {
            PermissionResult.ALLOW_ONCE: "[green]Allowed once[/green]",
            PermissionResult.ALLOW_ALL:  "[cyan]Allowed all[/cyan]",
            PermissionResult.DENY:       "[red]Denied[/red]",
        }
        self.mount(Label(labels[result], id="perm-answered"))
        if not self._future.done():
            self._future.set_result(result)


# ───────────────────────────────────────────────────────────────────────────────
class ToolCallCard(Widget):
    """
    Compact collapsible card for a tool call.
    Default: collapsed (shows only tool name + status icon in title).
    Expand to see parameters and result.
    """

    DEFAULT_CSS = """
    ToolCallCard {
        margin: 0 0 0 2;
        height: auto;
    }
    ToolCallCard Collapsible {
        border: round $warning;
        padding: 0;
        height: auto;
        background: $surface;
    }
    ToolCallCard .tool-params-label {
        color: $text-muted;
        margin: 0 1;
    }
    ToolCallCard .result-separator {
        color: $warning;
        margin: 0 1;
    }
    ToolCallCard .tool-result-label {
        color: $text;
        margin: 0 1 1 1;
    }
    ToolCallCard .tool-error-label {
        color: $error;
        margin: 0 1 1 1;
    }
    """

    def __init__(
        self,
        tool_name: str,
        tool_id: str,
        tool_input: dict,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._tool_id = tool_id
        self._tool_input = tool_input
        self._result: str | None = None
        self._is_error = False
        self._collapsible: Collapsible | None = None

    def _make_title(self) -> str:
        if self._result is None:
            return f"  ⧗ {self._tool_name}  (running...)"
        icon = "✘" if self._is_error else "✔"
        return f"  {icon} {self._tool_name}"

    def compose(self) -> ComposeResult:
        params_str = json.dumps(self._tool_input, ensure_ascii=False, indent=2)
        col = Collapsible(title=self._make_title(), collapsed=True)
        self._collapsible = col
        with col:
            # Parameters section
            yield Static(
                Syntax(params_str, "json", theme="monokai", word_wrap=True),
                classes="tool-params-label",
            )
            # Separator + result section (initially hidden until result arrives)
            yield Label("── Output ──", classes="result-separator", id="result-sep")
            yield Static(
                "running...",
                id="tool-result-ta",
                classes="tool-result-label",
                markup=False,
            )

    def set_result(self, result: str, is_error: bool = False) -> None:
        self._result = result
        self._is_error = is_error
        # Update collapsible title
        try:
            col = self.query_one(Collapsible)
            col.title = self._make_title()
        except Exception:
            pass
        # Update result text (markup=False prevents Rich from mis-parsing output)
        try:
            st = self.query_one("#tool-result-ta", Static)
            css_class = "tool-error-label" if is_error else "tool-result-label"
            st.set_classes(css_class)
            # Truncate very long results
            display = result if len(result) <= 3000 else result[:3000] + "\n...(truncated)"
            # Use Text object to avoid Rich markup interpretation
            from rich.text import Text
            st.update(Text(display))
        except Exception:
            pass


class ThinkingIndicator(Widget):
    """Animated 'thinking' indicator shown during API calls."""

    DEFAULT_CSS = """
    ThinkingIndicator {
        height: 3;
        margin: 1 0 0 2;
    }
    ThinkingIndicator LoadingIndicator {
        height: 1;
        width: 3;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield LoadingIndicator()
            yield Label("  Thinking...", markup=False)


# ──────────────────────────────────────────────────────────────────────────────
# Message list container
# ──────────────────────────────────────────────────────────────────────────────

class MessageList(ScrollableContainer):
    """
    Scrollable container that holds all conversation messages.
    Provides methods to add user/assistant messages and streaming updates.
    """

    DEFAULT_CSS = """
    MessageList {
        width: 1fr;
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
        background: $background;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current_assistant_bubble: AssistantBubble | None = None
        self._thinking: ThinkingIndicator | None = None
        # Maps tool_id → list of cards (same tool_id may appear multiple times
        # when the model returns non-unique ids like "call_fun")
        self._tool_cards: dict[str, list[ToolCallCard]] = {}
        self._card_seq: int = 0  # monotonically increasing, guarantees unique widget IDs

    # ── Public API ──────────────────────────────────────────────────────────

    def add_user_message(self, content: str) -> None:
        bubble = UserBubble(content)
        self.mount(bubble)
        self.scroll_end(animate=False)

    def begin_assistant_message(self) -> AssistantBubble:
        """Start a new streaming assistant message bubble."""
        self._remove_thinking()
        bubble = AssistantBubble(initial_text="")
        self._current_assistant_bubble = bubble
        self.mount(bubble)
        self.scroll_end(animate=False)
        return bubble

    def append_text_chunk(self, chunk: str) -> None:
        """Append a streaming text chunk to the current assistant bubble."""
        if self._current_assistant_bubble is None:
            self._current_assistant_bubble = self.begin_assistant_message()
        self._current_assistant_bubble.append_text(chunk)
        self.scroll_end(animate=False)

    def add_tool_call(self, tool_name: str, tool_id: str, tool_input: dict) -> None:
        """Add a tool call card (pending result)."""
        self._card_seq += 1
        widget_id = f"tool-card-{self._card_seq}"
        card = ToolCallCard(tool_name, tool_id, tool_input, id=widget_id)
        self._tool_cards.setdefault(tool_id, []).append(card)
        self.mount(card)
        self.scroll_end(animate=False)

    def add_permission_card(
        self,
        tool_name: str,
        description: str,
        future: asyncio.Future,
    ) -> PermissionCard:
        """Mount an inline permission card and return it."""
        self._card_seq += 1
        card = PermissionCard(
            tool_name, description, future,
            id=f"perm-card-{self._card_seq}",
        )
        self.mount(card)
        self.scroll_end(animate=False)
        return card

    def set_tool_result(self, tool_id: str, result: str, is_error: bool) -> None:
        """Update the *oldest pending* tool card matching tool_id with its result."""
        cards = self._tool_cards.get(tool_id, [])
        # Find the first card that hasn't received a result yet
        for card in cards:
            if card._result is None:
                card.set_result(result, is_error)
                break
        else:
            # Fallback: update the last card
            if cards:
                cards[-1].set_result(result, is_error)
        self.scroll_end(animate=False)

    def show_thinking(self) -> None:
        """Show the animated thinking indicator."""
        if self._thinking is None:
            self._thinking = ThinkingIndicator()
            self.mount(self._thinking)
            self.scroll_end(animate=False)

    def hide_thinking(self) -> None:
        self._remove_thinking()

    def add_system_message(self, text: str, style: str = "dim") -> None:
        """Add a system/status message (e.g. errors, info)."""
        if style:
            self.mount(Static(f"[{style}]{text}[/{style}]"))
        else:
            self.mount(Static(text))
        self.scroll_end(animate=False)

    def clear_messages(self) -> None:
        self._current_assistant_bubble = None
        self._thinking = None
        self._tool_cards.clear()
        self._card_seq = 0
        self.remove_children()

    def finish_assistant_message(self) -> None:
        """Called when the full response is complete."""
        self._current_assistant_bubble = None

    # ── Private helpers ─────────────────────────────────────────────────────

    def _remove_thinking(self) -> None:
        if self._thinking is not None:
            try:
                self._thinking.remove()
            except Exception:
                pass
            self._thinking = None
