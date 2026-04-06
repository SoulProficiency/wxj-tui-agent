"""
FileWriteTool: Create or overwrite a file (requires user permission).
"""
from __future__ import annotations

from pathlib import Path

from .base import ConfirmFn, PermissionResult, Tool


class FileWriteTool(Tool):
    name = "Write"
    description = (
        "Create a new file or overwrite an existing file with the given content. "
        "Parent directories are created automatically. "
        "Requires user permission."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to create/overwrite.",
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    }
    requires_permission = True

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        file_path: str = tool_input.get("file_path", "")
        content: str = tool_input.get("content", "")

        if not file_path:
            return "Error: file_path is required."

        description = f"Write {len(content)} characters to: {file_path}"
        permission = await self._request_permission(confirm_fn, tool_input, description)
        if permission == PermissionResult.DENY:
            return "File write denied by user."

        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {file_path}"
        except OSError as e:
            return f"Error writing file: {e}"
