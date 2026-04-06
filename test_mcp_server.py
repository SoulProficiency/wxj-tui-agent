#!/usr/bin/env python3
"""
Test MCP Server for python-tui-agent.

Provides 4 simple tools to verify MCP integration:
  - get_time        : return current datetime
  - calculator      : basic arithmetic (add/sub/mul/div)
  - list_directory  : list files in a directory
  - echo            : echo back a message

Usage:
  # stdio mode (used by MCP stdio transport)
  python test_mcp_server.py

  # SSE mode (HTTP server on port 8765)
  python test_mcp_server.py --sse [--port 8765]

  # WebSocket mode (WS server on port 8766)
  python test_mcp_server.py --ws [--port 8766]

Connect in TUI:
  stdio:  /mcp connect test {"type":"stdio","command":"D:\\anaconda\\python.exe","args":["d:\\argoProject\\opencode\\python-tui-agent\\test_mcp_server.py"]}
  sse:    /mcp connect test {"type":"sse","url":"http://localhost:8765/sse"}
  ws:     /mcp connect test {"type":"ws","url":"ws://localhost:8766/ws"}
"""
from __future__ import annotations

import argparse
import datetime
import math
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent

# ── Server setup ──────────────────────────────────────────────────────────────

app = Server("argo-test-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_time",
            description="Return the current date and time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "description": "strftime format string (default: '%Y-%m-%d %H:%M:%S')",
                    }
                },
            },
        ),
        Tool(
            name="calculator",
            description="Perform basic arithmetic: add, subtract, multiply, divide, power, sqrt.",
            inputSchema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide", "power", "sqrt"],
                        "description": "The arithmetic operation to perform.",
                    },
                    "a": {"type": "number", "description": "First operand."},
                    "b": {
                        "type": "number",
                        "description": "Second operand (not needed for sqrt).",
                    },
                },
                "required": ["operation", "a"],
            },
        ),
        Tool(
            name="list_directory",
            description="List files and directories at a given path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list (default: current working directory).",
                    },
                    "show_hidden": {
                        "type": "boolean",
                        "description": "Include hidden files (starting with dot). Default false.",
                    },
                },
            },
        ),
        Tool(
            name="echo",
            description="Echo back the provided message. Useful for testing connectivity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to echo back.",
                    }
                },
                "required": ["message"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "get_time":
        fmt = arguments.get("format", "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.now().strftime(fmt)
        return [TextContent(type="text", text=f"Current time: {now}")]

    elif name == "calculator":
        op = arguments.get("operation")
        a = float(arguments.get("a", 0))
        b = float(arguments.get("b", 0))
        try:
            if op == "add":
                result = a + b
            elif op == "subtract":
                result = a - b
            elif op == "multiply":
                result = a * b
            elif op == "divide":
                if b == 0:
                    return [TextContent(type="text", text="Error: division by zero")]
                result = a / b
            elif op == "power":
                result = a ** b
            elif op == "sqrt":
                if a < 0:
                    return [TextContent(type="text", text="Error: sqrt of negative number")]
                result = math.sqrt(a)
            else:
                return [TextContent(type="text", text=f"Unknown operation: {op}")]
            # Format: remove trailing zeros for clean output
            if result == int(result):
                result_str = str(int(result))
            else:
                result_str = f"{result:.6g}"
            return [TextContent(type="text", text=f"Result: {result_str}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif name == "list_directory":
        target = arguments.get("path", os.getcwd())
        show_hidden = arguments.get("show_hidden", False)
        try:
            p = Path(target)
            if not p.exists():
                return [TextContent(type="text", text=f"Path does not exist: {target}")]
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            lines = [f"Directory: {p.resolve()}"]
            for entry in entries:
                if not show_hidden and entry.name.startswith("."):
                    continue
                kind = "DIR " if entry.is_dir() else "FILE"
                size = ""
                if entry.is_file():
                    try:
                        size = f"  ({entry.stat().st_size:,} bytes)"
                    except OSError:
                        pass
                lines.append(f"  [{kind}] {entry.name}{size}")
            return [TextContent(type="text", text="\n".join(lines))]
        except Exception as e:
            return [TextContent(type="text", text=f"Error listing {target!r}: {e}")]

    elif name == "echo":
        msg = arguments.get("message", "")
        return [TextContent(type="text", text=f"Echo: {msg}")]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ── Entry point ───────────────────────────────────────────────────────────────

def run_stdio() -> None:
    """Run in stdio mode (default, for MCP stdio transport)."""
    import asyncio
    from mcp.server.stdio import stdio_server

    async def _main():
        async with stdio_server() as (read, write):
            init_options = app.create_initialization_options()
            await app.run(read, write, init_options)

    asyncio.run(_main())


def run_sse(port: int = 8765) -> None:
    """Run in SSE / HTTP mode for MCP SSE transport."""
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    print(f"[argo-test-server] SSE mode listening on http://localhost:{port}")
    print(f"  Connect with: /mcp connect test {{\"type\":\"sse\",\"url\":\"http://localhost:{port}/sse\"}}")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port, log_level="warning")


def run_ws(port: int = 8766) -> None:
    """Run in WebSocket mode for MCP WebSocket transport."""
    import uvicorn
    from mcp.server.websocket import websocket_server
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute

    async def handle_ws(websocket):
        async with websocket_server(websocket.scope, websocket.receive, websocket.send) as (read, write):
            await app.run(read, write, app.create_initialization_options())

    starlette_app = Starlette(
        routes=[
            WebSocketRoute("/ws", endpoint=handle_ws),
        ]
    )

    print(f"[argo-test-server] WebSocket mode listening on ws://localhost:{port}")
    print(f"  Connect in /setup MCP tab: type=ws, url=ws://localhost:{port}/ws")
    print(f"  Or via /mcp command:  /mcp connect test_ws {{\"type\":\"ws\",\"url\":\"ws://localhost:{port}/ws\"}}")
    uvicorn.run(starlette_app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Argo test MCP server")
    parser.add_argument("--sse", action="store_true", help="Run in SSE/HTTP mode instead of stdio")
    parser.add_argument("--ws",  action="store_true", help="Run in WebSocket mode")
    parser.add_argument("--port", type=int, default=None, help="Port (default: 8765 for sse, 8766 for ws)")
    args = parser.parse_args()

    if args.ws:
        run_ws(args.port or 8766)
    elif args.sse:
        run_sse(args.port or 8765)
    else:
        run_stdio()
