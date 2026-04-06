"""
FileEditTool: Precise str_replace editing (requires user permission).
Mirrors claude-code-haha's FileEditTool.
"""
from __future__ import annotations

from pathlib import Path

from .base import ConfirmFn, PermissionResult, Tool


class FileEditTool(Tool):
    name = "Edit"
    description = (
        "Edit a file by replacing an exact string with new text (str_replace). "
        "The old_string must match exactly once in the file. "
        "Use this for precise, targeted edits rather than rewriting the whole file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace (must be unique in the file).",
            },
            "new_string": {
                "type": "string",
                "description": "The replacement string.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }
    requires_permission = True

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        file_path: str = tool_input.get("file_path", "")
        old_string: str = tool_input.get("old_string", "")
        new_string: str = tool_input.get("new_string", "")

        if not file_path:
            return "Error: file_path is required."
        if old_string == new_string:
            return "Error: old_string and new_string are identical."

        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            return f"Error reading file: {e}"

        count = content.count(old_string)
        if count == 0:
            return (
                f"Error: old_string not found in {file_path}.\n"
                "Make sure the string matches exactly (including whitespace and newlines)."
            )
        if count > 1:
            return (
                f"Error: old_string found {count} times in {file_path}. "
                "It must be unique. Add more context to make it unique."
            )

        preview = f"Edit {file_path}: replace {len(old_string)} chars with {len(new_string)} chars"
        permission = await self._request_permission(confirm_fn, tool_input, preview)
        if permission == PermissionResult.DENY:
            return "File edit denied by user."

        new_content = content.replace(old_string, new_string, 1)
        try:
            path.write_text(new_content, encoding="utf-8")
            return f"Successfully edited {file_path}"
        except OSError as e:
            return f"Error writing file: {e}"
