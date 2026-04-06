"""
GlobTool: Find files matching a glob pattern.
"""
from __future__ import annotations

import glob as _glob
from pathlib import Path

from .base import ConfirmFn, Tool

_MAX_RESULTS = 500


class GlobTool(Tool):
    name = "Glob"
    description = (
        "Find files matching a glob pattern (e.g. '**/*.py', 'src/*.ts'). "
        f"Returns up to {_MAX_RESULTS} matching paths sorted alphabetically."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern, e.g. '**/*.py' or 'src/**/*.ts'.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for the glob (default: current directory).",
            },
        },
        "required": ["pattern"],
    }
    requires_permission = False

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        pattern: str = tool_input.get("pattern", "")
        cwd: str = tool_input.get("cwd", ".")

        if not pattern:
            return "Error: pattern is required."

        try:
            base = Path(cwd).resolve()
            matches = sorted(
                str(Path(p).resolve()) for p in _glob.glob(str(base / pattern), recursive=True)
            )
        except Exception as e:
            return f"Error: {e}"

        if not matches:
            return f"No files found matching '{pattern}' in '{cwd}'."

        truncated = matches[:_MAX_RESULTS]
        result = "\n".join(truncated)
        if len(matches) > _MAX_RESULTS:
            result += f"\n\n... ({len(matches) - _MAX_RESULTS} more results truncated)"
        return result
