"""
DailyManager: Generate and cache daily content for HealthTips + Logo theming.

File stored in ~/.config/pty-agent/memory/daily.md
Format:
  ## Date: YYYY-MM-DD
  ## Greeting: <morning/afternoon/evening greeting, personalized>
  ## Themes: keyword1, keyword2, keyword3
  ## News:
  - Headline or notable event 1
  - Headline or notable event 2
  - Headline or notable event 3
  ## Context:
  2-3 sentences about today.

Rules:
  - /newdaily: force regenerate (always calls LLM)
  - On startup: use cached if date matches today, else use fallback (no LLM)
  - LLM is only called explicitly via /newdaily
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AgentConfig

# ── Path ──────────────────────────────────────────────────────────────────────

MEMORY_DIR = Path.home() / ".config" / "wxj-agent" / "memory"
DAILY_FILE  = MEMORY_DIR / "daily.md"

# ── Prompt ────────────────────────────────────────────────────────────────────

_DAILY_PROMPT = """\
Today is {date} ({weekday}).

You are generating daily content for a developer's coding assistant app.
Search the web and return EXACTLY 15-20 real news headlines from today.

Rules:
- Search for real headlines from today ({date})
- Each headline: under 35 characters (hard limit, truncate if needed)
- Chinese for Chinese news, English for international news
- Mix: tech, politics, economy, sports, culture
- NO made-up or generic headlines

Output ONLY this markdown (no extra text, no preamble, no explanation):

## Date: {date}
## Greeting: [One warm greeting for a developer, max 60 chars, specific to {weekday}/{date}]
## Themes: [3-5 single keywords for today, comma-separated]
## News:
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
- [real headline ≤35 chars]
## Context:
[1-2 sentences about today]"""


# ── Public API ─────────────────────────────────────────────────────────────────

def load_daily() -> str:
    """
    Return today's daily.md if it exists and is dated today.
    Returns '' if missing or dated differently (no LLM call).
    """
    cached = _load_daily()
    today_str = date.today().isoformat()
    if cached and _is_today(cached, today_str):
        return cached
    return ""


async def force_update(config: "AgentConfig") -> tuple[bool, str]:
    """
    Force regenerate daily.md via LLM regardless of cache.
    Returns (success: bool, message: str).
    Called by /newdaily command.
    """
    today_str = date.today().isoformat()
    try:
        generated = await _generate_daily(config, today_str)
    except Exception as exc:
        # LLM call failed — write fallback and surface the error message
        fallback = _make_fallback(today_str)
        _save_daily(fallback)
        return False, f"LLM error: {exc}"

    # Validate: LLM response must contain ## Date: to be considered valid
    if generated and "## Date:" in generated:
        _save_daily(generated)
        return True, "daily.md updated successfully."

    # LLM returned empty or refused (e.g. "I'm sorry, but I can't help with that.")
    fallback = _make_fallback(today_str)
    _save_daily(fallback)
    if generated:  # non-empty but invalid format — LLM refused or hallucinated
        return False, f"LLM response was invalid (no ## Date: found), used built-in content. Response: {generated[:80]!r}"
    return False, "LLM unavailable — daily.md refreshed with built-in content."


def parse_greeting(daily_content: str) -> str:
    """Extract the Greeting line."""
    match = re.search(r"##\s*Greeting:\s*(.+)", daily_content, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_themes(daily_content: str) -> list[str]:
    """Extract the Themes line as a list of keywords."""
    match = re.search(r"##\s*Themes:\s*(.+)", daily_content, re.IGNORECASE)
    if not match:
        return []
    return [t.strip() for t in match.group(1).split(",") if t.strip()]


def parse_news(daily_content: str) -> list[str]:
    """Extract the News bullet items, truncated to 35 chars each."""
    match = re.search(
        r"##\s*News:\s*\n([\s\S]+?)(?=\n##|\Z)", daily_content, re.IGNORECASE
    )
    if not match:
        return []
    lines = match.group(1).strip().splitlines()
    items = []
    for line in lines:
        stripped = re.sub(r"^[-*]\s*", "", line.strip())
        if stripped:
            # Hard truncate to 34 chars + ellipsis if needed
            if len(stripped) > 34:
                stripped = stripped[:33] + "…"
            items.append(stripped)
    return items


def parse_context(daily_content: str) -> str:
    """Extract the Context section text."""
    match = re.search(
        r"##\s*Context:\s*\n([\s\S]+?)(?=\n##|\Z)", daily_content, re.IGNORECASE
    )
    return match.group(1).strip() if match else ""


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_daily() -> str:
    if DAILY_FILE.exists():
        try:
            return DAILY_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def _is_today(content: str, today_str: str) -> bool:
    match = re.search(r"##\s*Date:\s*(\d{4}-\d{2}-\d{2})", content)
    if not match:
        return False
    return match.group(1) == today_str


def _save_daily(content: str) -> None:
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        DAILY_FILE.write_text(content.strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def _make_fallback(today_str: str) -> str:
    """Rich fallback daily.md — no LLM needed."""
    d = date.fromisoformat(today_str)
    season = _get_season(d.month)
    weekday = d.strftime("%A")
    greeting_map = {
        "Monday":    "Happy Monday! A fresh week, a fresh start — let's build something great.",
        "Tuesday":   "Happy Tuesday! Momentum is building — keep the code flowing.",
        "Wednesday": "Midweek energy! You're halfway there — stay focused.",
        "Thursday":  "Almost Friday! Great things are just around the corner.",
        "Friday":    "Happy Friday! Ship something awesome before the weekend.",
        "Saturday":  "Weekend coding session! The best bugs hide on Saturdays.",
        "Sunday":    "Relaxed Sunday — perfect for exploring new ideas.",
    }
    greeting = greeting_map.get(weekday, f"Good day, developer! Today is {weekday}.")
    return (
        f"## Date: {today_str}\n"
        f"## Greeting: {greeting}\n"
        f"## Themes: {season}, creativity, technology, innovation, code\n"
        f"## News:\n"
        f"- Run /newdaily to load real news\n"
        f"- 天气：{season}季，适合天天写代码\n"
        f"- Python 3.13 新特性测试中\n"
        f"- GitHub Copilot 淡化初级工作\n"
        f"- 开源社区活跃：多个新PR合并\n"
        f"- AI 辅助编码效率提升80%\n"
        f"- Stack Overflow 年度调查发布\n"
        f"- 全球开发者超 1 亿\n"
        f"- Rust 连续 9 年最受欢迎语言\n"
        f"- 多差想大模型发布新版\n"
        f"- 远程办公常态化趋势\n"
        f"- Tech layoffs slow in Q2\n"
        f"- Open source AI gains traction\n"
        f"- Cloud costs rise 12% globally\n"
        f"- New CPU arch challenges x86\n"
        f"- Quantum computing hits milestone\n"
        f"## Context:\n"
        f"A {season} {weekday} full of possibilities. "
        f"The spirit of creation and exploration fills the air. "
        f"Today is a great day to build something new."
    )


def _get_season(month: int) -> str:
    if month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    elif month in (9, 10, 11):
        return "autumn"
    else:
        return "winter"


async def _generate_daily(config: "AgentConfig", today_str: str) -> str:
    """Call LLM to generate today's content. Returns '' on failure."""
    try:
        d = date.fromisoformat(today_str)
        weekday = d.strftime("%A")
        prompt = _DAILY_PROMPT.format(date=today_str, weekday=weekday)
        provider = getattr(config, "provider", "anthropic")

        if provider in ("aliyun", "openai"):
            # OpenAI-compatible path
            # enable_search lets qwen fetch real-time news; timeout is generous
            # because web search + generation can take 60-120 s.
            import httpx
            import openai as _openai
            client = _openai.AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0),
            )
            extra: dict = {}
            if provider == "aliyun":
                extra["extra_body"] = {"enable_search": True}
            response = await client.chat.completions.create(
                model=config.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                **extra,
            )
            text = response.choices[0].message.content if response.choices else ""
            return text.strip() if text else ""
        else:
            # Anthropic / MiniMax path
            import httpx
            import anthropic
            _timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)
            if config.auth_type == "bearer":
                client = anthropic.AsyncAnthropic(
                    api_key="dummy",
                    base_url=config.base_url,
                    default_headers={"Authorization": f"Bearer {config.api_key}"},
                    timeout=_timeout,
                )
            else:
                client = anthropic.AsyncAnthropic(
                    api_key=config.api_key,
                    base_url=config.base_url,
                    timeout=_timeout,
                )
            response = await client.messages.create(
                model=config.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            if not response.content:
                return ""
            for block in response.content:
                text = getattr(block, "text", None)
                if text is not None and text.strip():
                    return text.strip()
            return ""
    except Exception as exc:
        # Surface the error so force_update can log it
        raise RuntimeError(f"daily LLM call failed: {exc}") from exc
