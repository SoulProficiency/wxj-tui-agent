"""
Plan Mode: Right-side panel showing AI-managed task list.
- Activated by /plan command or Ctrl+P
- AI can write/update todos via PlanTool
- Renders PENDING/IN_PROGRESS/COMPLETE/CANCELLED items
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, Static

from agent.messages import TodoItem, TodoStatus
from agent.tools.base import ConfirmFn, Tool


# ──────────────────────────────────────────────────────────────────────────────
# PlanTool: AI-callable tool for managing the task list
# ──────────────────────────────────────────────────────────────────────────────

class PlanTool(Tool):
    """
    AI tool that writes and updates the task list (Plan Mode).
    The app registers a callback to receive updates.
    """

    name = "TodoWrite"
    description = (
        "Create or update the task list displayed in Plan Mode. "
        "Use this tool to track multi-step tasks. "
        "Provide a list of todo items, each with id, content, and status. "
        "Status values: PENDING, IN_PROGRESS, COMPLETE, CANCELLED. "
        "Set merge=true to update existing items; false to replace all."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "List of todo items.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Unique identifier."},
                        "content": {"type": "string", "description": "Task description."},
                        "status": {
                            "type": "string",
                            "enum": ["PENDING", "IN_PROGRESS", "COMPLETE", "CANCELLED"],
                        },
                    },
                    "required": ["id", "content", "status"],
                },
            },
            "merge": {
                "type": "boolean",
                "description": "If true, merge with existing items by id. If false, replace all.",
            },
        },
        "required": ["todos"],
    }
    requires_permission = False

    def __init__(self, on_update=None):
        self._on_update = on_update  # Callable[[list[TodoItem]], None]

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        raw_todos = tool_input.get("todos", [])
        merge: bool = tool_input.get("merge", False)

        items = []
        for t in raw_todos:
            try:
                items.append(TodoItem(
                    id=str(t["id"]),
                    content=str(t["content"]),
                    status=t.get("status", "PENDING"),
                ))
            except (KeyError, TypeError):
                continue

        if self._on_update:
            self._on_update(items, merge)

        return f"Updated {len(items)} todo item(s)."


# ──────────────────────────────────────────────────────────────────────────────
# TodoItemWidget: renders a single todo item
# ──────────────────────────────────────────────────────────────────────────────

_STATUS_COLOR = {
    "PENDING":     "dim",
    "IN_PROGRESS": "yellow",
    "COMPLETE":    "green",
    "CANCELLED":   "red",
}

_STATUS_ICON = {
    "PENDING":     "○",
    "IN_PROGRESS": "◐",
    "COMPLETE":    "●",
    "CANCELLED":   "✗",
}


class TodoItemWidget(Static):
    """Renders a single todo item row."""

    DEFAULT_CSS = """
    TodoItemWidget {
        height: auto;
        padding: 0 1;
        margin: 0;
    }
    """

    def __init__(self, item: TodoItem, **kwargs):
        super().__init__(**kwargs)
        self._item = item
        self._render()

    def _render(self) -> None:
        item = self._item
        color = _STATUS_COLOR.get(item.status, "dim")
        icon = _STATUS_ICON.get(item.status, "○")
        self.update(f"[{color}]{icon} {item.content}[/{color}]")

    def update_item(self, item: TodoItem) -> None:
        self._item = item
        self._render()


# ──────────────────────────────────────────────────────────────────────────────
# PlanPanel: the side panel widget
# ──────────────────────────────────────────────────────────────────────────────

class PlanPanel(Widget):
    """
    Side panel showing the current task list.
    Updated by PlanTool or manually by the user.
    """

    DEFAULT_CSS = """
    PlanPanel {
        width: 35;
        height: 1fr;
        background: $surface;
        border-left: solid $accent;
        padding: 0;
        display: none;
    }
    PlanPanel #plan-title {
        background: $accent;
        color: $background;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    PlanPanel #plan-empty {
        color: $text-muted;
        margin: 1;
        text-style: italic;
    }
    PlanPanel #plan-stats {
        color: $text-muted;
        padding: 0 1;
        height: 1;
    }
    PlanPanel ScrollableContainer {
        height: 1fr;
    }
    """

    todos: reactive[list[TodoItem]] = reactive([], layout=True)
    visible: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Label("  Plan", id="plan-title")
        yield Label("", id="plan-stats")
        with ScrollableContainer():
            yield Vertical(id="todo-list")
        yield Label("No tasks yet.", id="plan-empty")

    def watch_visible(self, visible: bool) -> None:
        self.styles.display = "block" if visible else "none"

    def watch_todos(self, todos: list[TodoItem]) -> None:
        self._rebuild()

    def toggle(self) -> None:
        self.visible = not self.visible

    def update_todos(self, new_items: list[TodoItem], merge: bool = False) -> None:
        if merge:
            existing = {t.id: t for t in self.todos}
            for item in new_items:
                existing[item.id] = item
            self.todos = list(existing.values())
        else:
            self.todos = list(new_items)

    def _rebuild(self) -> None:
        try:
            container = self.query_one("#todo-list", Vertical)
            container.remove_children()

            todos = self.todos
            empty_label = self.query_one("#plan-empty", Label)

            if not todos:
                empty_label.styles.display = "block"
                stats = ""
            else:
                empty_label.styles.display = "none"
                for item in todos:
                    container.mount(TodoItemWidget(item))

                done = sum(1 for t in todos if t.status == "COMPLETE")
                total = len(todos)
                stats = f" {done}/{total} done"

            try:
                self.query_one("#plan-stats", Label).update(stats)
            except Exception:
                pass

        except Exception:
            pass
