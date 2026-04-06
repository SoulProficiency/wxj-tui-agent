"""
Tool base class for Python TUI Agent.
All tools implement this interface.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable


# Permission result returned by the confirm function
class PermissionResult:
    ALLOW_ONCE = "allow_once"
    ALLOW_ALL = "allow_all"
    DENY = "deny"


ConfirmFn = Callable[[str, str, dict], Awaitable[str]]
"""
Signature: confirm_fn(tool_name, description, params) -> PermissionResult.*
"""


class Tool(ABC):
    """Abstract base class for all Agent tools."""

    name: str = ""
    description: str = ""
    input_schema: dict = {}
    # If True, the tool requires user permission before executing
    requires_permission: bool = False

    @abstractmethod
    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        """Execute the tool and return a string result."""
        ...

    def to_api_format(self) -> dict:
        """Convert to Anthropic API tool definition format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def format_params_preview(self, tool_input: dict) -> str:
        """Human-readable summary of input params for permission dialogs."""
        try:
            return json.dumps(tool_input, ensure_ascii=False, indent=2)
        except Exception:
            return str(tool_input)

    async def _request_permission(
        self,
        confirm_fn: ConfirmFn | None,
        tool_input: dict,
        description: str = "",
    ) -> str:
        """Request user permission; returns PermissionResult constant."""
        if confirm_fn is None:
            return PermissionResult.ALLOW_ONCE
        preview = self.format_params_preview(tool_input)
        return await confirm_fn(self.name, description or preview, tool_input)
