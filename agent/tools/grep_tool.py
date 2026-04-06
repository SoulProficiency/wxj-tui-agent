"""
GrepTool: Search file contents using regex.
Mirrors claude-code-haha's GrepTool.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import ConfirmFn, Tool

_MAX_RESULTS = 200


class GrepTool(Tool):
    name = "Grep"
    description = (
        "Search for a regex pattern across files. "
        "Returns matching lines with file path and line number. "
        f"Returns up to {_MAX_RESULTS} matches."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search. Defaults to current directory.",
            },
            "glob": {
                "type": "string",
                "description": "Glob pattern to filter files (e.g. '*.py'). Used when path is a directory.",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "If true, search is case-insensitive.",
            },
        },
        "required": ["pattern"],
    }
    requires_permission = False

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        pattern: str = tool_input.get("pattern", "")
        search_path: str = tool_input.get("path", ".")
        glob_pat: str = tool_input.get("glob", "**/*")
        case_insensitive: bool = tool_input.get("case_insensitive", False)

        if not pattern:
            return "Error: pattern is required."

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        base = Path(search_path)
        if not base.exists():
            return f"Error: Path not found: {search_path}"

        # Collect files
        if base.is_file():
            files = [base]
        else:
            import glob as _glob
            files = [
                Path(p) for p in _glob.glob(str(base / glob_pat), recursive=True)
                if Path(p).is_file()
            ]

        results: list[str] = []
        for file in sorted(files):
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{file}:{lineno}: {line.rstrip()}")
                    if len(results) >= _MAX_RESULTS:
                        break
            if len(results) >= _MAX_RESULTS:
                break

        if not results:
            return f"No matches found for '{pattern}'."

        output = "\n".join(results)
        if len(results) >= _MAX_RESULTS:
            output += f"\n\n... (results truncated at {_MAX_RESULTS} matches)"
        return output
