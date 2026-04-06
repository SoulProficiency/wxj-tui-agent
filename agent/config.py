"""
Configuration management for Python TUI Agent.
Reads/writes from ~/.config/pty-agent/config.json

Supports multiple named profiles (provider configurations).
The active profile is used for all LLM calls.

Provider types:
  - anthropic  : Anthropic API (x-api-key or bearer auth)
  - aliyun     : Alibaba Cloud Bailian (OpenAI-compatible, supports thinking)
  - minimax    : MiniMax API (Anthropic-compatible, supports thinking)
  - openai     : Generic OpenAI-compatible endpoint
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Optional

CONFIG_DIR  = Path.home() / ".config" / "wxj-agent"
CONFIG_FILE = CONFIG_DIR / "config.json"
SESSION_DIR = CONFIG_DIR / "sessions"

AuthType     = Literal["x-api-key", "bearer"]
ProviderType = Literal["anthropic", "aliyun", "minimax", "openai"]
PermissionMode = Literal["allow_all", "allow_safe", "ask_always", "deny_all"]

# Tools considered safe (read-only / low-risk)
SAFE_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "TodoRead"}

# Well-known provider defaults
PROVIDER_DEFAULTS: dict[str, dict] = {
    "anthropic": {
        "base_url":  "https://api.anthropic.com",
        "auth_type": "x-api-key",
        "model":     "claude-3-5-sonnet-20241022",
    },
    "aliyun": {
        "base_url":  "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "auth_type": "bearer",
        "model":     "qwen-plus",
    },
    "minimax": {
        "base_url":  "https://api.minimaxi.chat/v1",
        "auth_type": "bearer",
        "model":     "MiniMax-M2.7",
    },
    "openai": {
        "base_url":  "https://api.openai.com/v1",
        "auth_type": "bearer",
        "model":     "gpt-4o",
    },
}


@dataclass
class ModelProfile:
    """A named set of API credentials + model parameters."""
    name: str = "default"
    provider: ProviderType = "anthropic"
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-3-5-sonnet-20241022"
    auth_type: AuthType = "x-api-key"
    max_tokens: int = 8192

    # Thinking / reasoning params (provider-specific)
    enable_thinking: bool = False
    thinking_budget: int = 1024   # tokens allocated to thinking

    # Web search (aliyun qwen only)
    enable_search: bool = False

    # Sampling params (omitted from request if set to sentinel -1.0)
    temperature: float = -1.0    # -1.0 = not set (use provider default)
    top_p: float = -1.0          # -1.0 = not set

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ModelProfile":
        known = {f.name for f in ModelProfile.__dataclass_fields__.values()}  # type: ignore
        return ModelProfile(**{k: v for k, v in d.items() if k in known})


@dataclass
class AgentConfig:
    """Full application config: active profile + global settings."""

    # ── Active profile (flattened for easy access by existing code) ───────────
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-3-5-sonnet-20241022"
    auth_type: AuthType = "x-api-key"
    max_tokens: int = 8192
    provider: ProviderType = "anthropic"

    # Thinking
    enable_thinking: bool = False
    thinking_budget: int = 1024

    # Web search (aliyun qwen only)
    enable_search: bool = False

    # Sampling
    temperature: float = -1.0
    top_p: float = -1.0

    # ── Global settings ───────────────────────────────────────────────────────
    theme: Literal["dark", "light"] = "dark"
    auto_approve_tools: list[str] = field(default_factory=list)
    mcp_servers: dict[str, dict] = field(default_factory=dict)
    skills_dir: str = ""
    cwd: str = ""
    max_context_messages: int = 40
    permission_mode: str = "ask_always"
    # Context compression settings
    # compress_threshold: when msg count exceeds this, call LLM to summarize older msgs
    # hard_limit: when msg count exceeds this, forcibly truncate after LLM summarization
    compress_threshold: int = 10
    hard_limit: int = 20
    # TodoWrite / Plan Mode behaviour
    # "auto"     — AI decides when to use TodoWrite (default)
    # "priority" — AI is strongly encouraged to always use TodoWrite for multi-step tasks
    # "direct"   — AI focuses on quick replies; suggests switching for complex tasks
    todo_mode: str = "auto"

    # ── Saved profiles (name → profile dict) ─────────────────────────────────
    profiles: dict[str, dict] = field(default_factory=dict)
    active_profile: str = ""   # name of active profile; "" means manual/unsaved

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def to_dict(self) -> dict:
        return asdict(self)

    def apply_profile(self, profile: ModelProfile) -> None:
        """Copy profile fields into active config."""
        self.name         = profile.name  # type: ignore[attr-defined]
        self.provider     = profile.provider
        self.api_key      = profile.api_key
        self.base_url     = profile.base_url
        self.model        = profile.model
        self.auth_type    = profile.auth_type
        self.max_tokens   = profile.max_tokens
        self.enable_thinking = profile.enable_thinking
        self.thinking_budget = profile.thinking_budget
        self.enable_search   = profile.enable_search
        self.temperature  = profile.temperature
        self.top_p        = profile.top_p
        self.active_profile = profile.name

    def to_profile(self) -> ModelProfile:
        """Export current active settings as a ModelProfile."""
        return ModelProfile(
            name=self.active_profile or "current",
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            auth_type=self.auth_type,
            max_tokens=self.max_tokens,
            enable_thinking=self.enable_thinking,
            thinking_budget=self.thinking_budget,
            enable_search=self.enable_search,
            temperature=self.temperature,
            top_p=self.top_p,
        )

    def save_profile(self, profile: ModelProfile) -> None:
        """Add/update a named profile in the profiles dict."""
        self.profiles[profile.name] = profile.to_dict()

    def delete_profile(self, name: str) -> None:
        self.profiles.pop(name, None)
        if self.active_profile == name:
            self.active_profile = ""

    def list_profiles(self) -> list[ModelProfile]:
        return [ModelProfile.from_dict(d) for d in self.profiles.values()]


def load_config() -> AgentConfig:
    """Load config from file, then apply environment variable overrides."""
    cfg = AgentConfig()

    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            known = {f.name for f in AgentConfig.__dataclass_fields__.values()}  # type: ignore
            for key, value in data.items():
                if key in known:
                    setattr(cfg, key, value)
        except (json.JSONDecodeError, OSError):
            pass

    # If an active_profile is recorded, apply it so the live fields
    # (model, api_key, base_url …) always match the chosen profile.
    if cfg.active_profile and cfg.active_profile in cfg.profiles:
        try:
            profile = ModelProfile.from_dict(cfg.profiles[cfg.active_profile])
            cfg.apply_profile(profile)
        except Exception:
            pass

    # Environment variable overrides (legacy support)
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg.api_key = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        cfg.api_key = os.environ["ANTHROPIC_AUTH_TOKEN"]
        cfg.auth_type = "bearer"
    if os.environ.get("ANTHROPIC_BASE_URL"):
        cfg.base_url = os.environ["ANTHROPIC_BASE_URL"]
    if os.environ.get("ANTHROPIC_MODEL"):
        cfg.model = os.environ["ANTHROPIC_MODEL"]

    return cfg


def save_config(cfg: AgentConfig) -> None:
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
