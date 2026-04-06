"""
MCP (Model Context Protocol) client for Python TUI Agent.

Supports three transport modes:
  - stdio   : local subprocess via stdin/stdout
  - sse     : remote HTTP Server-Sent Events
  - http    : remote Streamable HTTP (MCP 1.x)
  - ws      : WebSocket

Each connected MCP server exposes tools that are wrapped as MCPTool instances
and registered with the QueryEngine alongside local tools.

Tool naming: "{server_name}__{tool_name}"  (mirrors claude-code-haha buildMcpToolName)
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.websocket import websocket_client

from .tools.base import ConfirmFn, Tool


# ── Config dataclasses ────────────────────────────────────────────────────────

@dataclass
class MCPStdioConfig:
    type: Literal["stdio"] = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPSSEConfig:
    type: Literal["sse"] = "sse"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPHTTPConfig:
    type: Literal["http"] = "http"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPWebSocketConfig:
    type: Literal["ws"] = "ws"
    url: str = ""


MCPServerConfig = MCPStdioConfig | MCPSSEConfig | MCPHTTPConfig | MCPWebSocketConfig


def parse_mcp_config(name: str, raw: dict) -> MCPServerConfig:
    """Parse a raw config dict (from JSON/config file) into a typed config."""
    t = raw.get("type", "stdio")
    if t == "stdio":
        return MCPStdioConfig(
            command=raw.get("command", ""),
            args=raw.get("args", []),
            env=raw.get("env", {}),
        )
    elif t == "sse":
        return MCPSSEConfig(url=raw.get("url", ""), headers=raw.get("headers", {}))
    elif t == "http":
        return MCPHTTPConfig(url=raw.get("url", ""), headers=raw.get("headers", {}))
    elif t == "ws":
        return MCPWebSocketConfig(url=raw.get("url", ""))
    else:
        raise ValueError(f"Unknown MCP transport type {t!r} for server {name!r}")


# ── MCPTool wrapper ───────────────────────────────────────────────────────────

class MCPTool(Tool):
    """
    Wraps a remote MCP tool as a local Tool so QueryEngine can use it.
    Tool name format: "{server_name}__{tool_name}"
    """

    requires_permission: bool = True

    def __init__(self, client: "MCPClient", server_name: str, tool_def: dict) -> None:
        self._client = client
        self._server_name = server_name
        self._raw_tool_name = tool_def["name"]
        self.name = f"{server_name}__{self._raw_tool_name}"
        self.description = (
            f"[MCP:{server_name}] {tool_def.get('description', '')}"
        )
        self.input_schema = tool_def.get("inputSchema") or tool_def.get("input_schema") or {
            "type": "object",
            "properties": {},
        }

    async def execute(self, tool_input: dict, confirm_fn: ConfirmFn | None = None) -> str:
        if confirm_fn:
            result = await confirm_fn(self.name, tool_input)
            from .tools.base import PermissionResult
            if result == PermissionResult.DENY:
                return "Tool execution denied by user."
        return await self._client.call_tool(self._raw_tool_name, tool_input)


# ── MCPClient ─────────────────────────────────────────────────────────────────

class MCPClient:
    """
    Manages a single MCP server connection.
    Uses anyio task groups (via asynccontextmanager) internally.
    """

    def __init__(self, name: str, config: MCPServerConfig) -> None:
        self.name = name
        self.config = config
        self._session: ClientSession | None = None
        self._tools: list[dict] = []
        self._exit_stack: Any = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Establish connection and fetch tool list."""
        cfg = self.config

        if isinstance(cfg, MCPStdioConfig):
            env = {**os.environ, **cfg.env} if cfg.env else None
            params = StdioServerParameters(
                command=cfg.command,
                args=cfg.args,
                env=env,
            )
            ctx = stdio_client(params)
        elif isinstance(cfg, MCPSSEConfig):
            ctx = sse_client(url=cfg.url, headers=cfg.headers or None)
        elif isinstance(cfg, MCPHTTPConfig):
            ctx = streamablehttp_client(url=cfg.url, headers=cfg.headers or None)
        elif isinstance(cfg, MCPWebSocketConfig):
            ctx = websocket_client(url=cfg.url)
        else:
            raise ValueError(f"Unsupported config type: {type(cfg)}")

        # Enter the transport context manager manually so we can keep the
        # connection open for the lifetime of the client.
        self._transport_ctx = ctx
        transport_result = await ctx.__aenter__()

        # stdio returns (read, write); sse/ws returns (read, write);
        # streamablehttp returns (read, write, session_url_fn)
        if isinstance(transport_result, tuple) and len(transport_result) == 3:
            read, write, _ = transport_result
        else:
            read, write = transport_result

        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()

        # Fetch available tools
        tools_result = await self._session.list_tools()
        self._tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema.model_dump() if hasattr(t.inputSchema, "model_dump") else (t.inputSchema or {}),
            }
            for t in tools_result.tools
        ]
        self._connected = True

    async def disconnect(self) -> None:
        """Close the connection cleanly."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
        if self._transport_ctx:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._transport_ctx = None
        self._connected = False
        self._tools = []

    async def list_tools(self) -> list[dict]:
        """Return cached tool definitions."""
        return list(self._tools)

    async def call_tool(self, tool_name: str, tool_input: dict) -> str:
        """Call a tool and return its text result."""
        if not self._session:
            return "Error: MCP server not connected."
        try:
            result = await self._session.call_tool(tool_name, tool_input)
            # Extract text from content blocks
            parts: list[str] = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "data"):
                    parts.append(f"[binary data: {len(block.data)} bytes]")
                else:
                    parts.append(str(block))
            output = "\n".join(parts)
            if result.isError:
                return f"MCP tool error: {output}"
            return output
        except Exception as e:
            return f"Error calling MCP tool {tool_name!r}: {e}"


# ── MCPManager ────────────────────────────────────────────────────────────────

class MCPManager:
    """
    Manages multiple MCP server connections.
    Provides a unified tool list for QueryEngine.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    async def connect_server(self, name: str, config: MCPServerConfig) -> MCPClient:
        """Connect to a new MCP server (or reconnect if already registered)."""
        if name in self._clients:
            await self.disconnect_server(name)

        client = MCPClient(name, config)
        try:
            await client.connect()
            self._clients[name] = client
        except Exception as e:
            raise RuntimeError(f"Failed to connect MCP server {name!r}: {e}") from e
        return client

    async def connect_server_from_raw(self, name: str, raw: dict) -> MCPClient:
        """Parse raw dict config and connect."""
        config = parse_mcp_config(name, raw)
        return await self.connect_server(name, config)

    async def disconnect_server(self, name: str) -> None:
        """Disconnect a named server."""
        if name in self._clients:
            await self._clients[name].disconnect()
            del self._clients[name]

    async def disconnect_all(self) -> None:
        """Disconnect all servers."""
        for client in list(self._clients.values()):
            await client.disconnect()
        self._clients.clear()

    def get_all_tools(self) -> list[Tool]:
        """
        Return all MCP tools as MCPTool instances.
        Only includes tools from connected servers.
        """
        tools: list[Tool] = []
        for name, client in self._clients.items():
            if client.is_connected:
                for tool_def in client._tools:
                    tools.append(MCPTool(client, name, tool_def))
        return tools

    @property
    def server_names(self) -> list[str]:
        return list(self._clients.keys())

    def get_status(self) -> list[tuple[str, bool, int]]:
        """Return list of (server_name, is_connected, tool_count)."""
        return [
            (name, client.is_connected, len(client._tools))
            for name, client in self._clients.items()
        ]
