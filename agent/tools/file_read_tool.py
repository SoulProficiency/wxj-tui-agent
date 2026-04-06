"""
FileReadTool: Read file contents with optional line range.
"""
from __future__ import annotations

from pathlib import Path

from .base import ConfirmFn, Tool

_MAX_LINES = 2000


class FileReadTool(Tool):
    name = "Read"
    description = (
        "Read the contents of a file. "
        "Optionally specify start_line and end_line (1-based, inclusive) to read a range. "
        f"Returns at most {_MAX_LINES} lines."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file.",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-based). Optional.",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read (1-based, inclusive). Optional.",
            },
        },
        "required": ["file_path"],
    }
    requires_permission = False

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        file_path: str = tool_input.get("file_path", "")
        start_line: int | None = tool_input.get("start_line")
        end_line: int | None = tool_input.get("end_line")

        if not file_path:
            return "Error: file_path is required."

        path = Path(file_path)
        if not path.exists():
            return f"Error: File not found: {file_path}"
        if not path.is_file():
            return f"Error: Not a file: {file_path}"

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"Error reading file: {e}"

        lines = content.splitlines(keepends=True)
        total = len(lines)

        # Apply line range
        s = (start_line - 1) if start_line else 0
        e = end_line if end_line else total
        s = max(0, min(s, total))
        e = max(s, min(e, total))

        # Enforce max lines
        if e - s > _MAX_LINES:
            e = s + _MAX_LINES

        selected = lines[s:e]
        numbered = "".join(
            f"{s + i + 1:6}→{line}" for i, line in enumerate(selected)
        )

        header = f"File: {file_path} (lines {s+1}-{s+len(selected)} of {total})\n"
        return header + numbered
