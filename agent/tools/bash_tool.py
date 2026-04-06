"""
BashTool: Execute shell commands (requires user permission).
Mirrors claude-code-haha's BashTool.
"""
from __future__ import annotations

import asyncio
import locale
import os
import re
import sys
from typing import Optional

from .base import ConfirmFn, PermissionResult, Tool

_TIMEOUT = 120  # seconds

# Strip ANSI escape sequences (color codes, cursor movements, etc.)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHFJABCDSTsu]|\x1b\][^\x07]*\x07|\x1b[=>]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes so TUI displays plain text without garbled chars."""
    return _ANSI_RE.sub("", text)


def _decode_output(raw: bytes) -> str:
    """
    Decode subprocess bytes to str.
    On Windows: try UTF-8 first, then system OEM encoding (GBK on Chinese Windows).
    """
    if sys.platform == "win32":
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
        # Fall back to system OEM encoding
        try:
            enc = locale.getpreferredencoding(False) or "gbk"
            return raw.decode(enc, errors="replace")
        except Exception:
            return raw.decode("gbk", errors="replace")
    return raw.decode("utf-8", errors="replace")


class BashTool(Tool):
    name = "Bash"
    description = (
        "Execute a bash/shell command in the current working directory. "
        "Use for running scripts, git commands, build tools, etc. "
        "Commands run with a 120-second timeout. "
        "IMPORTANT: Only run commands you are confident are safe."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Optional timeout in seconds (default 120).",
            },
            "description": {
                "type": "string",
                "description": "Short description of what this command does, shown to the user.",
            },
        },
        "required": ["command"],
    }
    requires_permission = True

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        command: str = tool_input.get("command", "")
        timeout: int = tool_input.get("timeout", _TIMEOUT)
        description: str = tool_input.get("description", f"$ {command}")

        if not command.strip():
            return "Error: Empty command."

        # Request permission
        permission = await self._request_permission(confirm_fn, tool_input, description)
        if permission == PermissionResult.DENY:
            return "Command execution denied by user."

        # Run the command
        try:
            env = os.environ.copy()
            if sys.platform == "win32":
                # Request UTF-8 from subprocesses where possible
                env["PYTHONIOENCODING"] = "utf-8"
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            else:
                # Disable color output on Unix so ANSI codes are minimized
                env["TERM"] = "dumb"
                env["NO_COLOR"] = "1"
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    executable="/bin/bash",
                    env=env,
                )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return f"Error: Command timed out after {timeout} seconds."

            output_parts = []
            if stdout:
                decoded = _strip_ansi(_decode_output(stdout))
                output_parts.append(decoded.rstrip())
            if stderr:
                decoded_err = _strip_ansi(_decode_output(stderr))
                output_parts.append(f"[stderr]\n{decoded_err.rstrip()}")
            if proc.returncode != 0:
                output_parts.append(f"[exit code: {proc.returncode}]")

            return "\n".join(output_parts) if output_parts else "(no output)"

        except Exception as e:
            return f"Error executing command: {e}"
