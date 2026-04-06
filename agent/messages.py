"""
Message type definitions for Python TUI Agent.
Mirrors the message types from claude-code-haha's types/message.ts.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


def _new_id() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────
# Content block types (mirror Anthropic SDK)
# ─────────────────────────────────────────────

@dataclass
class TextBlock:
    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    type: Literal["tool_use"] = "tool_use"
    id: str = field(default_factory=_new_id)
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class ToolResultBlock:
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock


# ─────────────────────────────────────────────
# Message types (for conversation history)
# ─────────────────────────────────────────────

@dataclass
class UserMessage:
    content: str | list[ContentBlock]
    id: str = field(default_factory=_new_id)
    role: Literal["user"] = "user"

    def to_api_format(self) -> dict:
        if isinstance(self.content, str):
            return {"role": "user", "content": self.content}
        blocks = []
        for block in self.content:
            if isinstance(block, ToolResultBlock):
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                    "is_error": block.is_error,
                })
            else:
                blocks.append({"type": "text", "text": block.text if isinstance(block, TextBlock) else str(block)})
        return {"role": "user", "content": blocks}


@dataclass
class AssistantMessage:
    content: list[ContentBlock]
    id: str = field(default_factory=_new_id)
    role: Literal["assistant"] = "assistant"

    def text(self) -> str:
        """Concatenate all text blocks."""
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def to_api_format(self) -> dict:
        blocks = []
        for block in self.content:
            if isinstance(block, TextBlock):
                blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return {"role": "assistant", "content": blocks}


# ─────────────────────────────────────────────
# Plan / Todo types (for Plan Mode)
# ─────────────────────────────────────────────

TodoStatus = Literal["PENDING", "IN_PROGRESS", "COMPLETE", "CANCELLED"]


@dataclass
class TodoItem:
    id: str
    content: str
    status: TodoStatus = "PENDING"

    def status_icon(self) -> str:
        icons = {
            "PENDING": "○",
            "IN_PROGRESS": "◐",
            "COMPLETE": "●",
            "CANCELLED": "✗",
        }
        return icons.get(self.status, "○")


# ─────────────────────────────────────────────
# Session serialization helpers
# ─────────────────────────────────────────────

def messages_to_api(messages: list[UserMessage | AssistantMessage]) -> list[dict]:
    """Convert internal message list to Anthropic API format."""
    return [m.to_api_format() for m in messages]
