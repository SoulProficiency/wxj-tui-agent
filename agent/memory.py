"""
MemoryManager: Persistent conversation memory backed by Markdown files.

Files stored in ~/.config/pty-agent/memory/
  conversation_summary.md  — rolling LLM summary of past conversations
  user_habits.md           — behavioral habits (code style, tools, workflow) — max 20 bullets
  user_info.md             — personal profile (language pref, communication style, frameworks)
                             closed-loop update: stabilizes over time, not append-only

Strategy:
  - Short-term: recent N messages stay in RAM (normal context window)
  - Long-term: every N rounds (compress_threshold), summarize the batch asynchronously.
               Each new batch summary is MERGED with the existing summary via LLM
               (old_summary + new_batch → one refined summary), preventing unbounded growth.
  - On session start: inject MD summary into system prompt
  - After each session: async update user_habits.md AND user_info.md via LLM
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AgentConfig

# ── Paths ─────────────────────────────────────────────────────────────────────

MEMORY_DIR   = Path.home() / ".config" / "wxj-agent" / "memory"
SUMMARY_FILE = MEMORY_DIR / "conversation_summary.md"
HABITS_FILE  = MEMORY_DIR / "user_habits.md"
INFO_FILE    = MEMORY_DIR / "user_info.md"

# How many recent messages to keep in RAM before summarizing older ones
SHORT_TERM_KEEP = 20

# Maximum bullet points kept in user_habits.md
HABITS_MAX_BULLETS = 20

# ── Prompts ───────────────────────────────────────────────────────────────────

_SUMMARIZE_PROMPT = """\
The following are old conversation messages between a user and Argo (an AI coding assistant).
Summarize the key facts, decisions, code changes, and outcomes in concise bullet points.
Focus on information that would be useful in a future conversation.
Write in English. Be brief but complete.

Messages:
{messages_json}

Output a markdown bullet list only, no preamble."""

_MERGE_SUMMARY_PROMPT = """\
You are maintaining a rolling summary of past conversations between a user and Argo (an AI coding assistant).

Existing summary (may be long):
{existing_summary}

New conversation batch summary:
{new_batch_summary}

Task: Merge and REFINE the above two summaries into ONE concise summary.
Rules:
- Combine overlapping or related points — do NOT simply concatenate.
- Remove outdated or superseded information if the new batch contradicts it.
- Keep total length SHORT: aim for ≤ 20 bullet points covering the most important facts.
- Output a markdown bullet list ONLY, no preamble, no headers.
- Write in English."""

_HABITS_PROMPT = """\
You are tracking the behavioral habits of a user working with Argo (an AI coding assistant).
Focus ONLY on observable coding behaviors: code style choices, preferred tools, workflow patterns,
command preferences, file naming conventions, testing habits, etc.

Previous habits (merge/update, do NOT simply append):
{existing_habits}

New conversation:
{messages_json}

Rules:
- Output ONLY a markdown bullet list
- Maximum {max_bullets} bullets total — if over limit, merge similar items or drop least relevant
- Merge with existing habits, never duplicate
- Remove outdated habits if new evidence contradicts them"""

_INFO_PROMPT = """\
You are maintaining a stable personal profile of a user who works with Argo (an AI coding assistant).
Focus on STABLE personal characteristics: preferred languages, communication style, project domains,
technology stack preferences, learning style, and any personal context relevant to coding assistance.

Current profile (refine this, do NOT just append):
{existing_info}

New conversation:
{messages_json}

Rules:
- Output ONLY a markdown bullet list (no headers, no preamble)
- Maximum 15 bullets
- This profile should STABILIZE over time — only update if new evidence is strong
- Merge and refine rather than adding new bullets for every conversation
- If a bullet is already accurate, keep it exactly as is"""


# ── MemoryManager ─────────────────────────────────────────────────────────────

class MemoryManager:
    """Manages persistent memory files and LLM-based summarization."""

    def __init__(self, config: "AgentConfig") -> None:
        self.config = config
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    # ── Read helpers ──────────────────────────────────────────────────────────

    def load_summary(self) -> str:
        """Return the current conversation summary MD text, or empty string."""
        if SUMMARY_FILE.exists():
            try:
                return SUMMARY_FILE.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    def load_habits(self) -> str:
        """Return the current user habits MD text, or empty string."""
        if HABITS_FILE.exists():
            try:
                return HABITS_FILE.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    def load_info(self) -> str:
        """Return the current user info/profile MD text, or empty string."""
        if INFO_FILE.exists():
            try:
                return INFO_FILE.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    def build_memory_section(self) -> str:
        """Build the memory block to inject into the system prompt."""
        parts: list[str] = []

        summary = self.load_summary()
        if summary:
            parts.append("## Past Conversation Summary\n" + summary)

        habits = self.load_habits()
        if habits:
            parts.append("## User Behavioral Habits\n" + habits)

        info = self.load_info()
        if info:
            parts.append("## User Personal Profile\n" + info)

        if not parts:
            return ""
        return "\n\n".join(parts)

    # ── Write helpers ─────────────────────────────────────────────────────────

    def _write_summary(self, summary_md: str) -> None:
        """Overwrite the summary file with a refined summary."""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"# Conversation Summary\n_Last updated: {timestamp}_\n\n"
        SUMMARY_FILE.write_text(header + summary_md.strip() + "\n", encoding="utf-8")

    def _write_habits(self, habits_md: str) -> None:
        """Overwrite the habits file, enforcing HABITS_MAX_BULLETS limit."""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        # Trim bullet list to max allowed
        trimmed = _trim_bullets(habits_md, HABITS_MAX_BULLETS)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"# User Behavioral Habits\n_Last updated: {timestamp}_\n\n"
        HABITS_FILE.write_text(header + trimmed.strip() + "\n", encoding="utf-8")

    def _write_info(self, info_md: str) -> None:
        """Overwrite the user info/profile file (closed-loop, stabilizing update)."""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"# User Personal Profile\n_Last updated: {timestamp}_\n\n"
        INFO_FILE.write_text(header + info_md.strip() + "\n", encoding="utf-8")

    # ── LLM calls ─────────────────────────────────────────────────────────────

    async def summarize_messages(self, messages: list) -> str:
        """
        Call the LLM to summarize a list of messages.
        Returns a markdown bullet string, or "" on failure.
        """
        messages_json = _messages_to_text(messages)
        prompt = _SUMMARIZE_PROMPT.format(messages_json=messages_json)
        return await self._call_llm(prompt, max_tokens=1024)

    async def update_habits(self, messages: list) -> None:
        """
        Analyze the session messages and update user_habits.md (max HABITS_MAX_BULLETS).
        Runs silently — errors are swallowed.
        """
        try:
            existing = self.load_habits()
            messages_json = _messages_to_text(messages)
            prompt = _HABITS_PROMPT.format(
                existing_habits=existing or "(none yet)",
                messages_json=messages_json,
                max_bullets=HABITS_MAX_BULLETS,
            )
            result = await self._call_llm(prompt, max_tokens=1024)
            if result:
                self._write_habits(result)
        except Exception:
            pass  # never surface memory errors to user

    async def update_info(self, messages: list) -> None:
        """
        Analyze the session messages and update user_info.md (closed-loop profile).
        Runs silently — errors are swallowed.
        """
        try:
            existing = self.load_info()
            messages_json = _messages_to_text(messages)
            prompt = _INFO_PROMPT.format(
                existing_info=existing or "(no profile yet)",
                messages_json=messages_json,
            )
            result = await self._call_llm(prompt, max_tokens=1024)
            if result:
                self._write_info(result)
        except Exception:
            pass  # never surface memory errors to user

    async def merge_summaries(self, existing_summary: str, new_batch_summary: str) -> str:
        """
        Merge the existing rolling summary with a new batch summary into one refined summary.
        Returns the merged text, or falls back to concatenation on failure.
        """
        if not existing_summary.strip():
            return new_batch_summary
        if not new_batch_summary.strip():
            return existing_summary
        prompt = _MERGE_SUMMARY_PROMPT.format(
            existing_summary=existing_summary.strip(),
            new_batch_summary=new_batch_summary.strip(),
        )
        merged = await self._call_llm(prompt, max_tokens=1024)
        if merged:
            return merged
        # Fallback: simple concatenation (better than losing data)
        return existing_summary.strip() + "\n" + new_batch_summary.strip()

    async def compress_and_summarize(self, old_messages: list) -> str:
        """
        Summarize old_messages, then MERGE with the existing rolling summary
        (refining rather than appending), and overwrite the summary file.
        Returns the new merged summary text.
        """
        new_batch = await self.summarize_messages(old_messages)
        if not new_batch:
            return ""
        existing = self.load_summary()
        merged = await self.merge_summaries(existing, new_batch)
        if merged:
            self._write_summary(merged)
        return merged

    # ── Client builder ────────────────────────────────────────────────────────

    def _build_client(self):
        """Build an LLM client appropriate for the configured provider."""
        cfg = self.config
        provider = getattr(cfg, "provider", "anthropic")
        if provider in ("aliyun", "openai"):
            import openai as _openai
            return _openai.AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        # Anthropic / MiniMax / others via anthropic SDK
        import anthropic
        if cfg.auth_type == "bearer":
            return anthropic.AsyncAnthropic(
                api_key="dummy",
                base_url=cfg.base_url,
                default_headers={"Authorization": f"Bearer {cfg.api_key}"},
            )
        return anthropic.AsyncAnthropic(api_key=cfg.api_key, base_url=cfg.base_url)

    def _is_openai_provider(self) -> bool:
        return getattr(self.config, "provider", "anthropic") in ("aliyun", "openai")

    async def _call_llm(self, prompt: str, max_tokens: int = 1024) -> str:
        """Call the LLM with a single-turn prompt; returns text or ''."""
        try:
            client = self._build_client()
            if self._is_openai_provider():
                resp = await client.chat.completions.create(
                    model=self.config.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content or ""
            else:
                resp = await client.messages.create(
                    model=self.config.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return _extract_text(resp.content) if resp.content else ""
        except Exception:
            return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(content: list) -> str:
    """
    Extract text from an Anthropic response content list.
    Skips ThinkingBlock / RedactedThinkingBlock (which have no .text),
    returns the first TextBlock's text.
    """
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return ""


def _trim_bullets(md_text: str, max_count: int) -> str:
    """
    Parse bullet lines from md_text and keep at most max_count.
    Bullets are lines starting with '- ' or '* '.
    Non-bullet lines (headers, blank) are preserved as-is before the bullets.
    """
    lines = md_text.strip().splitlines()
    bullets: list[str] = []
    others: list[str] = []
    in_bullets = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            in_bullets = True
            bullets.append(line)
        elif not in_bullets:
            others.append(line)
        # once in bullet section, skip non-bullet lines (headers inserted by _write_habits)

    # Keep only the LATEST max_count bullets
    if len(bullets) > max_count:
        bullets = bullets[-max_count:]

    result_lines = others + bullets
    return "\n".join(result_lines)


def _messages_to_text(messages: list) -> str:
    """Convert internal message objects to a compact readable text."""
    lines: list[str] = []
    for m in messages:
        try:
            api = m.to_api_format() if hasattr(m, "to_api_format") else {}
            role = api.get("role", "?")
            content = api.get("content", "")
            if isinstance(content, str):
                lines.append(f"[{role}]: {content[:500]}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype == "text":
                            lines.append(f"[{role}/text]: {block.get('text','')[:500]}")
                        elif btype == "tool_use":
                            lines.append(f"[{role}/tool_use]: {block.get('name','')} "
                                         f"{json.dumps(block.get('input',{}))[:200]}")
                        elif btype == "tool_result":
                            lines.append(f"[{role}/tool_result]: "
                                         f"{str(block.get('content',''))[:300]}")
        except Exception:
            pass
    return "\n".join(lines)
