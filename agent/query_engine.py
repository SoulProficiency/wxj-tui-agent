"""
QueryEngine: Core LLM query loop with tool calling.
Mirrors claude-code-haha's QueryEngine.ts agentic loop.

Flow:
  1. Send messages + tools to API (streaming)
  2. Accumulate text and tool_use blocks
  3. For each tool_use: request permission → execute → collect result
  4. Append assistant + user (tool results) messages, loop
  5. Stop when stop_reason == "end_turn" or no tool uses
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Awaitable
from typing import Any

import anthropic
import openai as _openai

from .config import AgentConfig
from .memory import MemoryManager
from .messages import (
    AssistantMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    messages_to_api,
)
from .tools import DEFAULT_TOOLS, ConfirmFn, Tool
from .skills import SkillLoader
from .mcp_client import MCPManager

# Max agentic loop iterations to prevent infinite loops
_MAX_ITERATIONS = 30
# Extended limit for allow_all permission mode (requires user confirmation to continue)
_MAX_ITERATIONS_EXTENDED = 100

# Rough token estimator: 1 token ≈ 4 chars
def _estimate_tokens(messages: list) -> int:
    total = 0
    for m in messages:
        api = m.to_api_format() if hasattr(m, 'to_api_format') else {}
        content = api.get('content', '')
        if isinstance(content, str):
            total += len(content) // 4
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get('text', '') or block.get('content', ''))) // 4
    return total


def _find_safe_trim_point(messages: list, keep_tail: int) -> int:
    """
    Find the oldest index we can safely trim to WITHOUT breaking
    tool_use / tool_result pairing.

    Rules:
      - Never split a (assistant-with-tool_use, user-with-tool_result) pair.
      - The returned slice messages[idx:] is always API-valid.
    """
    if keep_tail >= len(messages):
        return 0

    candidate = len(messages) - keep_tail

    # Walk backwards from candidate to find a safe cut point:
    # a safe cut is right after a complete tool-result user message,
    # or at a plain user/assistant boundary.
    for idx in range(candidate, -1, -1):
        if idx == 0:
            return 0
        msg = messages[idx]
        api = msg.to_api_format() if hasattr(msg, 'to_api_format') else {}
        role = api.get('role', '')
        content = api.get('content', [])
        # A plain user text message is always a safe cut point
        if role == 'user':
            if isinstance(content, str):
                return idx
            if isinstance(content, list):
                types = {b.get('type') for b in content if isinstance(b, dict)}
                if types == {'text'} or not types:
                    return idx
                # user message that is tool_result — only safe if idx+1 exists
                # and is assistant (i.e., the pair is complete above this point)
                if 'tool_result' in types and idx > 0:
                    return idx
        elif role == 'assistant':
            # assistant message with only text (no tool_use) is also safe
            if isinstance(content, list):
                types = {b.get('type') for b in content if isinstance(b, dict)}
                if 'tool_use' not in types:
                    return idx
    return 0

# Callback types
OnTextChunk = Callable[[str], None]
OnToolUse = Callable[[str, str, dict], None]   # name, id, input
OnToolResult = Callable[[str, str, bool], None]  # id, result, is_error
OnContextUpdate = Callable[[int, int, bool], None]  # turns, est_tokens, was_compressed
OnTurnStart = Callable[[], None]   # called when a new LLM generation round begins
OnTurnEnd = Callable[[bool], None] # called when a round ends; arg=has_tool_calls
# Called when the normal 30-round limit is hit in allow_all mode.
# Receives current iteration count; must return True to continue (up to 100), False to stop.
OnIterationLimit = Callable[[int], Awaitable[bool]]
# Called when a background compression is in progress and the next query must wait.
# on_compression_wait(True) = compression started/waiting; on_compression_wait(False) = done
OnCompressionWait = Callable[[bool], None]


class QueryEngine:
    """
    Manages the conversation state and runs the agentic tool-calling loop.
    """

    def __init__(
        self,
        config: AgentConfig,
        extra_tools: list[Tool] | None = None,
        mcp_manager: MCPManager | None = None,
    ) -> None:
        self.config = config
        self._extra_tools: list[Tool] = extra_tools or []
        self._mcp_manager = mcp_manager
        self._skill_loader = SkillLoader(
            skills_dir=config.skills_dir or None
        )
        self._rebuild_tool_map()
        # Auto-approve set (updated when user picks "allow all" in TUI)
        self.auto_approved: set[str] = set(config.auto_approve_tools)
        self._abort = False
        self._memory = MemoryManager(config)
        # ── Async compression state ────────────────────────────────────────────
        # Counts how many user<->assistant round-trips have completed
        self._turn_count: int = 0
        # Messages collected for the next compression batch
        self._pending_compress_msgs: list = []
        # The in-flight background compression task (or None)
        self._compression_task: asyncio.Task | None = None

    def _rebuild_tool_map(self) -> None:
        """Rebuild the active tools list including MCP tools."""
        mcp_tools = self._mcp_manager.get_all_tools() if self._mcp_manager else []
        self.tools: list[Tool] = list(DEFAULT_TOOLS) + self._extra_tools + mcp_tools
        self._tool_map: dict[str, Tool] = {t.name: t for t in self.tools}

    def abort(self) -> None:
        """Signal the running query to abort."""
        self._abort = True

    def _compress_messages(
        self,
        messages: list,
    ) -> tuple[list, bool]:
        """
        Trim messages for the current query call only.
    
        This no longer triggers compression directly — compression is handled
        asynchronously by _maybe_schedule_compression().
    
        The hard_limit still applies here as a safety valve: if the message
        list has grown beyond hard_limit (e.g., compression task was delayed),
        we forcibly truncate to prevent API 400 errors.
        """
        hard_lim = getattr(self.config, "hard_limit", 20)
        n = len(messages)
        if n <= hard_lim:
            return messages, False
    
        # Hard safety truncation only
        trim_idx = _find_safe_trim_point(messages, hard_lim)
        if trim_idx == 0:
            return messages, False
    
        head = [messages[0]] if trim_idx > 0 else []
        tail = messages[trim_idx:]
        return head + tail, True
    
    def _maybe_schedule_compression(
        self,
        new_messages: list,
        on_compression_done: "Callable[[], None] | None" = None,
    ) -> None:
        """
        Called after each stream_query completes.
        Accumulates messages and launches a background compression task
        once compress_threshold rounds have passed.
        The task runs fully asynchronously — the user can keep chatting.
        on_compression_done: optional zero-arg callback invoked when the task finishes.
        """
        threshold = getattr(self.config, "compress_threshold", 10)
    
        # Accumulate every message returned by this round
        self._pending_compress_msgs.extend(new_messages)
        self._turn_count += 1
    
        if self._turn_count < threshold:
            return
        if self._compression_task and not self._compression_task.done():
            # Previous compression still running; don't double-schedule
            return
    
        # Snapshot the batch and reset counters
        batch = list(self._pending_compress_msgs)
        self._pending_compress_msgs = []
        self._turn_count = 0
    
        async def _run_and_notify() -> None:
            await self._memory.compress_and_summarize(batch)
            if on_compression_done:
                try:
                    on_compression_done()
                except Exception:
                    pass
    
        self._compression_task = asyncio.ensure_future(_run_and_notify())

    def _is_openai_provider(self) -> bool:
        """Returns True for providers that use the OpenAI-compatible chat/completions API."""
        return getattr(self.config, "provider", "anthropic") in ("aliyun", "openai")

    def _build_client(self) -> anthropic.AsyncAnthropic:
        cfg = self.config
        extra_headers: dict[str, str] = {}
        if cfg.auth_type == "bearer":
            extra_headers["Authorization"] = f"Bearer {cfg.api_key}"
            return anthropic.AsyncAnthropic(
                api_key="dummy",
                base_url=cfg.base_url,
                default_headers=extra_headers,
            )
        return anthropic.AsyncAnthropic(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )

    def _build_openai_client(self) -> _openai.AsyncOpenAI:
        """Build an async OpenAI-compatible client for aliyun/openai providers."""
        cfg = self.config
        return _openai.AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )

    def _build_stream_kwargs(self) -> dict:
        """
        Build extra keyword arguments for client.messages.stream().

        Provider-specific thinking params (per official docs):
          - anthropic: top-level  thinking={type, budget_tokens}
          - aliyun:    extra_body {enable_thinking: true, thinking_budget: N}
                       (enable_thinking is NOT an OpenAI-standard param, must go in extra_body)
          - minimax:   top-level  thinking={type, budget_tokens}
                       (MiniMax Anthropic-compat API supports thinking as a native top-level param)
          - sampling:  temperature / top_p only included when user explicitly set them (>= 0)
        """
        cfg = self.config
        kwargs: dict = {}

        # Sampling params — only include if user explicitly set them
        if cfg.temperature >= 0:
            kwargs["temperature"] = cfg.temperature
        if cfg.top_p >= 0:
            kwargs["top_p"] = cfg.top_p

        # Provider-specific thinking params
        provider = getattr(cfg, "provider", "anthropic")

        if provider == "aliyun" and cfg.enable_thinking:
            # Aliyun Bailian: must use extra_body (non-standard OpenAI param)
            # Ref: https://help.aliyun.com/zh/model-studio/deep-thinking
            kwargs["extra_body"] = {
                "enable_thinking": True,
                "thinking_budget": cfg.thinking_budget,
            }

        elif provider == "minimax" and cfg.enable_thinking:
            # MiniMax Anthropic-compatible API: thinking is a TOP-LEVEL param
            # Ref: https://platform.minimaxi.com/docs/api-reference/text-anthropic-api
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": cfg.thinking_budget,
            }

        elif provider == "anthropic" and cfg.enable_thinking:
            # Native Anthropic thinking (claude-3-7+ models)
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": cfg.thinking_budget,
            }

        return kwargs

    def _tools_api(self) -> list[dict]:
        # Rebuild tool map to pick up any newly connected MCP tools
        self._rebuild_tool_map()
        return [t.to_api_format() for t in self.tools]

    def _tools_openai_api(self) -> list[dict]:
        """Convert tools to OpenAI function-calling format."""
        self._rebuild_tool_map()
        result = []
        for t in self.tools:
            anthr = t.to_api_format()  # {name, description, input_schema}
            result.append({
                "type": "function",
                "function": {
                    "name": anthr["name"],
                    "description": anthr.get("description", ""),
                    "parameters": anthr.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return result

    def _build_openai_stream_kwargs(self) -> dict:
        """Build extra kwargs for OpenAI-compatible stream calls."""
        cfg = self.config
        kwargs: dict = {}
        if cfg.temperature >= 0:
            kwargs["temperature"] = cfg.temperature
        if cfg.top_p >= 0:
            kwargs["top_p"] = cfg.top_p
        # Aliyun-specific extra_body options
        if getattr(cfg, "provider", "") == "aliyun":
            extra: dict = {}
            if cfg.enable_thinking:
                extra["enable_thinking"] = True
                extra["thinking_budget"] = cfg.thinking_budget
            if getattr(cfg, "enable_search", False):
                extra["enable_search"] = True
            if extra:
                kwargs["extra_body"] = extra
        return kwargs

    def _build_system_prompt(self, base: str) -> str:
        """
        Augment the base system prompt with memory, Skills context and MCP server info.
        """
        parts = [base]

        # Long-term memory section (summary + habits)
        memory_section = self._memory.build_memory_section()
        if memory_section:
            parts.append("## Long-term Memory\n" + memory_section)

        # Skills section
        skills_section = self._skill_loader.get_system_prompt_section()
        if skills_section:
            parts.append(skills_section)

        # MCP section
        if self._mcp_manager:
            statuses = self._mcp_manager.get_status()
            if statuses:
                mcp_lines = ["\n## Connected MCP Servers"]
                for name, connected, tool_count in statuses:
                    status_str = f"{tool_count} tools" if connected else "disconnected"
                    mcp_lines.append(f"- **{name}**: {status_str}")
                parts.append("\n".join(mcp_lines))

        return "\n".join(parts)

    async def stream_query(
        self,
        messages: list[UserMessage | AssistantMessage],
        system_prompt: str,
        on_text: OnTextChunk,
        on_tool_use: OnToolUse,
        on_tool_result: OnToolResult,
        confirm_fn: ConfirmFn | None,
        on_context_update: OnContextUpdate | None = None,
        on_turn_start: "OnTurnStart | None" = None,
        on_turn_end: "OnTurnEnd | None" = None,
        on_iteration_limit: "OnIterationLimit | None" = None,
        on_compression_wait: "OnCompressionWait | None" = None,
        on_compression_done: "Callable[[], None] | None" = None,
    ) -> list[UserMessage | AssistantMessage]:
        """
        Run the agentic loop, streaming text tokens and executing tools.
        Routes to OpenAI-compatible loop for aliyun/openai providers.

        Background compression:
          - If a previous round triggered background compression and it hasn't
            finished yet, we await it here (calling on_compression_wait to show
            a TUI indicator) so the summary is ready for the system prompt.
          - After this query completes, _maybe_schedule_compression() decides
            whether to launch a new background compression task.

        Iteration limits:
          - Normal: up to _MAX_ITERATIONS (30) rounds.
          - allow_all mode: on reaching 30, on_iteration_limit() is called.
            If it returns True, continue up to _MAX_ITERATIONS_EXTENDED (100);
            otherwise stop. If on_iteration_limit is None, always stop at 30.
        """
        self._abort = False

        # ── Wait for in-flight compression before sending (so summary is fresh) ──
        if self._compression_task and not self._compression_task.done():
            if on_compression_wait:
                on_compression_wait(True)
            try:
                await self._compression_task
            except Exception:
                pass
            if on_compression_wait:
                on_compression_wait(False)

        # Safety hard-limit truncation (only if context grew beyond hard_limit).
        # This is a silent safety valve — we do NOT surface it as a user-visible
        # "Context compressed" message (that's reserved for the async compression flow).
        compressed, was_hard_truncated = self._compress_messages(messages)
        if was_hard_truncated and on_context_update:
            est = _estimate_tokens(compressed)
            on_context_update(len(compressed), est, False)  # False = no chat-area banner

        if self._is_openai_provider():
            new_messages = await self._stream_query_openai(
                compressed, system_prompt,
                on_text, on_tool_use, on_tool_result,
                confirm_fn, on_turn_start, on_turn_end,
                on_iteration_limit,
            )
        else:
            new_messages = await self._stream_query_anthropic(
                compressed, system_prompt,
                on_text, on_tool_use, on_tool_result,
                confirm_fn, on_turn_start, on_turn_end,
                on_iteration_limit,
            )

        # Report final context stats regardless of which provider was used.
        # Always pass was_compressed=False here — the async compression task is
        # handled separately; we never want a "Context compressed" banner from here.
        if on_context_update:
            on_context_update(len(new_messages), _estimate_tokens(new_messages), False)

        # Schedule background compression (fire-and-forget, non-blocking)
        self._maybe_schedule_compression(new_messages, on_compression_done=on_compression_done)

        return new_messages

    # ── Anthropic-native loop ───────────────────────────────────────────────

    async def _stream_query_anthropic(
        self,
        compressed: list,
        system_prompt: str,
        on_text: OnTextChunk,
        on_tool_use: OnToolUse,
        on_tool_result: OnToolResult,
        confirm_fn: ConfirmFn | None,
        on_turn_start: "OnTurnStart | None" = None,
        on_turn_end: "OnTurnEnd | None" = None,
        on_iteration_limit: "OnIterationLimit | None" = None,
    ) -> list[UserMessage | AssistantMessage]:
        client = self._build_client()
        api_messages = messages_to_api(compressed)
        new_messages: list[UserMessage | AssistantMessage] = list(compressed)
        was_compressed = False  # already handled by caller
        # When True, the user approved continuing past _MAX_ITERATIONS
        _extended = False

        for iteration in range(_MAX_ITERATIONS_EXTENDED):
            if self._abort:
                break

            # ── Iteration limit check ──────────────────────────────────────
            if iteration == _MAX_ITERATIONS and not _extended:
                # In allow_all mode, ask the user whether to continue
                if (
                    self.config.permission_mode == "allow_all"
                    and on_iteration_limit is not None
                ):
                    keep_going = await on_iteration_limit(iteration)
                    if keep_going:
                        _extended = True
                    else:
                        break
                else:
                    # Not allow_all or no callback → hard stop
                    break

            # Hard stop at extended limit
            if _extended and iteration >= _MAX_ITERATIONS_EXTENDED:
                break

            # ── Stream API response ────────────────────────────────────────
            # Notify UI: new LLM generation round is starting
            if on_turn_start:
                on_turn_start()

            text_chunks: list[str] = []
            tool_uses: list[ToolUseBlock] = []

            try:
                stream_kwargs = self._build_stream_kwargs()
                async with client.messages.stream(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    system=self._build_system_prompt(system_prompt),
                    messages=api_messages,
                    tools=self._tools_api(),
                    **stream_kwargs,
                ) as stream:
                    # Accumulate tool input JSON per tool_use id
                    current_tool_id: str | None = None
                    current_tool_name: str | None = None
                    tool_input_buffers: dict[str, list[str]] = {}

                    async for event in stream:
                        if self._abort:
                            break

                        etype = event.type

                        if etype == "content_block_start":
                            block = event.content_block
                            if block.type == "tool_use":
                                current_tool_id = block.id
                                current_tool_name = block.name
                                tool_input_buffers[block.id] = []

                        elif etype == "content_block_delta":
                            delta = event.delta
                            if delta.type == "text_delta":
                                chunk = delta.text
                                text_chunks.append(chunk)
                                on_text(chunk)
                            elif delta.type == "input_json_delta" and current_tool_id:
                                tool_input_buffers[current_tool_id].append(delta.partial_json)

                        elif etype == "content_block_stop":
                            if current_tool_id and current_tool_name:
                                raw_json = "".join(tool_input_buffers.get(current_tool_id, []))
                                try:
                                    tool_input_data = json.loads(raw_json) if raw_json else {}
                                except json.JSONDecodeError:
                                    tool_input_data = {}
                                tub = ToolUseBlock(
                                    id=current_tool_id,
                                    name=current_tool_name,
                                    input=tool_input_data,
                                )
                                tool_uses.append(tub)
                                on_tool_use(current_tool_name, current_tool_id, tool_input_data)
                                current_tool_id = None
                                current_tool_name = None

                    final_message = await stream.get_final_message()
                    stop_reason = final_message.stop_reason

            except anthropic.APIError as e:
                on_text(f"\n\n**API Error**: {e}\n")
                break
            except Exception as e:
                on_text(f"\n\n**Error**: {e}\n")
                break

            # ── Build assistant message ───────────────────────────────────
            content_blocks: list[TextBlock | ToolUseBlock] = []
            if text_chunks:
                content_blocks.append(TextBlock(text="".join(text_chunks)))
            content_blocks.extend(tool_uses)

            asst_msg = AssistantMessage(content=content_blocks)
            new_messages.append(asst_msg)
            api_messages.append(asst_msg.to_api_format())

            # Notify UI: this generation round is complete
            if on_turn_end:
                on_turn_end(bool(tool_uses))

            # ── No tool calls → done ───────────────────────────────────────
            if not tool_uses or stop_reason == "end_turn":
                break

            # ── Execute each tool ─────────────────────────────────────────
            tool_results: list[ToolResultBlock] = []
            for tub in tool_uses:
                if self._abort:
                    break

                tool = self._tool_map.get(tub.name)
                if tool is None:
                    result_content = f"Error: Unknown tool '{tub.name}'."
                    is_error = True
                else:
                    # Build confirm_fn with auto-approve logic
                    effective_confirm = self._make_confirm_fn(tub.name, confirm_fn)
                    try:
                        result_content = await tool.execute(tub.input, effective_confirm)
                        is_error = result_content.startswith("Error:")
                    except Exception as e:
                        result_content = f"Error executing {tub.name}: {e}"
                        is_error = True

                on_tool_result(tub.id, result_content, is_error)
                tool_results.append(
                    ToolResultBlock(
                        tool_use_id=tub.id,
                        content=result_content,
                        is_error=is_error,
                    )
                )

            # ── Append tool results as user message ───────────────────────
            if tool_results:
                user_result_msg = UserMessage(content=tool_results)
                new_messages.append(user_result_msg)
                api_messages.append(user_result_msg.to_api_format())

        return new_messages

    def _make_confirm_fn(self, tool_name: str, confirm_fn: ConfirmFn | None) -> ConfirmFn | None:
        """Wrap confirm_fn with auto-approve logic."""
        from .tools.base import PermissionResult

        if tool_name in self.auto_approved:
            async def auto_approve(tn: str, desc: str, params: dict) -> str:
                return PermissionResult.ALLOW_ONCE
            return auto_approve

        if confirm_fn is None:
            return None

        # Intercept ALLOW_ALL to update auto_approved set
        engine = self

        async def wrapped(tn: str, desc: str, params: dict) -> str:
            result = await confirm_fn(tn, desc, params)
            if result == PermissionResult.ALLOW_ALL:
                engine.auto_approved.add(tn)
            return result

        return wrapped

    # ── OpenAI-compatible loop (aliyun / openai) ──────────────────────────

    async def _stream_query_openai(
        self,
        compressed: list,
        system_prompt: str,
        on_text: OnTextChunk,
        on_tool_use: OnToolUse,
        on_tool_result: OnToolResult,
        confirm_fn: ConfirmFn | None,
        on_turn_start: "OnTurnStart | None" = None,
        on_turn_end: "OnTurnEnd | None" = None,
        on_iteration_limit: "OnIterationLimit | None" = None,
    ) -> list[UserMessage | AssistantMessage]:
        """
        OpenAI-compatible agentic loop for aliyun/openai providers.
        Uses openai.AsyncOpenAI with chat.completions streaming.
        """
        client = self._build_openai_client()
        system_content = self._build_system_prompt(system_prompt)
        tools = self._tools_openai_api()
        stream_kwargs = self._build_openai_stream_kwargs()

        # Build initial message list: system + history
        oai_messages: list[dict] = [{"role": "system", "content": system_content}]
        for m in compressed:
            fmt = m.to_api_format()
            role = fmt["role"]
            content = fmt["content"]
            # Flatten Anthropic content blocks to OpenAI format
            if isinstance(content, list):
                # tool_result blocks  → tool messages
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        oai_messages.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        })
                    elif isinstance(block, dict) and block.get("type") == "tool_use":
                        # skip — already captured as assistant tool_calls below
                        pass
                    elif isinstance(block, dict) and block.get("type") == "text":
                        oai_messages.append({"role": role, "content": block["text"]})
            else:
                oai_messages.append({"role": role, "content": content or ""})

        new_messages: list[UserMessage | AssistantMessage] = list(compressed)
        # When True, the user approved continuing past _MAX_ITERATIONS
        _extended = False

        import uuid
        for iteration in range(_MAX_ITERATIONS_EXTENDED):
            if self._abort:
                break

            # ── Iteration limit check ──────────────────────────────────────
            if iteration == _MAX_ITERATIONS and not _extended:
                if (
                    self.config.permission_mode == "allow_all"
                    and on_iteration_limit is not None
                ):
                    keep_going = await on_iteration_limit(iteration)
                    if keep_going:
                        _extended = True
                    else:
                        break
                else:
                    break

            if _extended and iteration >= _MAX_ITERATIONS_EXTENDED:
                break

            if on_turn_start:
                on_turn_start()

            text_chunks: list[str] = []
            tool_calls_raw: dict[int, dict] = {}  # index → accumulated call

            try:
                stream = await client.chat.completions.create(
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    messages=oai_messages,
                    tools=tools if tools else _openai.NOT_GIVEN,
                    tool_choice="auto" if tools else _openai.NOT_GIVEN,
                    stream=True,
                    **stream_kwargs,
                )

                finish_reason = None
                async for chunk in stream:
                    if self._abort:
                        break
                    choice = chunk.choices[0] if chunk.choices else None
                    if choice is None:
                        continue
                    finish_reason = choice.finish_reason or finish_reason
                    delta = choice.delta

                    # Text
                    if delta.content:
                        text_chunks.append(delta.content)
                        on_text(delta.content)

                    # Tool calls (streamed incrementally)
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_raw:
                                tool_calls_raw[idx] = {
                                    "id": tc.id or "",
                                    "name": "",
                                    "args_buf": "",
                                }
                            if tc.id:
                                tool_calls_raw[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_raw[idx]["name"] += tc.function.name
                                if tc.function.arguments:
                                    tool_calls_raw[idx]["args_buf"] += tc.function.arguments

            except _openai.APIError as e:
                on_text(f"\n\n**API Error**: {e}\n")
                break
            except Exception as e:
                on_text(f"\n\n**Error**: {e}\n")
                break

            # Build ToolUseBlock list from accumulated tool calls
            tool_uses: list[ToolUseBlock] = []
            oai_tool_calls_for_msg = []
            for raw in tool_calls_raw.values():
                tc_id = raw["id"] or f"call_{uuid.uuid4().hex[:8]}"
                tc_name = raw["name"]
                try:
                    tc_input = json.loads(raw["args_buf"]) if raw["args_buf"] else {}
                except json.JSONDecodeError:
                    tc_input = {}
                tub = ToolUseBlock(id=tc_id, name=tc_name, input=tc_input)
                tool_uses.append(tub)
                on_tool_use(tc_name, tc_id, tc_input)
                oai_tool_calls_for_msg.append({
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": tc_name, "arguments": raw["args_buf"]},
                })

            # Build assistant message
            content_blocks: list[TextBlock | ToolUseBlock] = []
            if text_chunks:
                content_blocks.append(TextBlock(text="".join(text_chunks)))
            content_blocks.extend(tool_uses)
            asst_msg = AssistantMessage(content=content_blocks)
            new_messages.append(asst_msg)

            # Add assistant turn to OAI history
            asst_oai: dict = {"role": "assistant", "content": "".join(text_chunks) or None}
            if oai_tool_calls_for_msg:
                asst_oai["tool_calls"] = oai_tool_calls_for_msg
            oai_messages.append(asst_oai)

            if on_turn_end:
                on_turn_end(bool(tool_uses))

            if not tool_uses or finish_reason == "stop":
                break

            # Execute tools
            tool_results: list[ToolResultBlock] = []
            for tub in tool_uses:
                if self._abort:
                    break
                tool = self._tool_map.get(tub.name)
                if tool is None:
                    result_content = f"Error: Unknown tool '{tub.name}'."
                    is_error = True
                else:
                    effective_confirm = self._make_confirm_fn(tub.name, confirm_fn)
                    try:
                        result_content = await tool.execute(tub.input, effective_confirm)
                        is_error = result_content.startswith("Error:")
                    except Exception as e:
                        result_content = f"Error executing {tub.name}: {e}"
                        is_error = True

                on_tool_result(tub.id, result_content, is_error)
                tool_results.append(
                    ToolResultBlock(
                        tool_use_id=tub.id,
                        content=result_content,
                        is_error=is_error,
                    )
                )
                # Append tool result to OAI messages
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tub.id,
                    "content": result_content,
                })

            if tool_results:
                user_result_msg = UserMessage(content=tool_results)
                new_messages.append(user_result_msg)

        return new_messages
