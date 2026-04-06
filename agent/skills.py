"""
Skills loader for Python TUI Agent.

Skills are Markdown files stored in ~/.config/wxj-agent/skills/*.md
Each file uses YAML frontmatter to declare metadata, and the Markdown body
is injected into the LLM system prompt when the skill is active.

Frontmatter format:
---
name: my-skill
description: "What this skill does"
when_to_use: "When the user needs to do X"
allowed_tools: [Bash, Read, Write]
argument_hint: "<target-file>"
---
The skill prompt body goes here (sent to LLM as system context).

Mirrors claude-code-haha's loadSkillsDir.ts PromptCommand pattern.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import CONFIG_DIR


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class SkillConfig:
    """Represents a single loaded Skill from a .md file."""
    name: str
    description: str
    content: str                       # Markdown body (system prompt payload)
    source_file: Path
    when_to_use: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    argument_hint: str = ""

    def __repr__(self) -> str:
        return f"<Skill name={self.name!r} file={self.source_file.name!r}>"


# ── Parser ────────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_skill_file(path: Path) -> SkillConfig | None:
    """
    Parse a .md file into a SkillConfig.
    Returns None if the file is missing required frontmatter fields.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    m = _FRONTMATTER_RE.match(raw)
    if not m:
        # No frontmatter — treat filename (sans .md) as the skill name,
        # entire file as content.
        return SkillConfig(
            name=path.stem,
            description=f"Skill loaded from {path.name}",
            content=raw.strip(),
            source_file=path,
        )

    fm_text, body = m.group(1), m.group(2).strip()
    try:
        fm: dict[str, Any] = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return None

    name = fm.get("name") or path.stem
    description = fm.get("description") or ""
    if isinstance(description, list):
        description = " ".join(str(d) for d in description)
    else:
        description = str(description)

    raw_tools = fm.get("allowed_tools", [])
    if isinstance(raw_tools, str):
        allowed_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
    else:
        allowed_tools = [str(t) for t in (raw_tools or [])]

    return SkillConfig(
        name=str(name),
        description=description,
        content=body,
        source_file=path,
        when_to_use=str(fm.get("when_to_use") or ""),
        allowed_tools=allowed_tools,
        argument_hint=str(fm.get("argument_hint") or ""),
    )


# ── SkillLoader ───────────────────────────────────────────────────────────────

class SkillLoader:
    """
    Loads Skills from ~/.config/wxj-agent/skills/*.md (or a custom dir).

    Usage:
        loader = SkillLoader()
        skills = loader.load_all()
        section = loader.get_system_prompt_section()
    """

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        if skills_dir:
            self.skills_dir = Path(skills_dir)
        else:
            self.skills_dir = CONFIG_DIR / "skills"
        self._cache: list[SkillConfig] | None = None

    def load_all(self, force_reload: bool = False) -> list[SkillConfig]:
        """
        Scan skills_dir for *.md files and return parsed SkillConfig list.
        Results are cached until force_reload=True.
        """
        if self._cache is not None and not force_reload:
            return self._cache

        if not self.skills_dir.exists():
            self._cache = []
            return self._cache

        skills: list[SkillConfig] = []
        for md_file in sorted(self.skills_dir.glob("*.md")):
            skill = _parse_skill_file(md_file)
            if skill is not None:
                skills.append(skill)

        self._cache = skills
        return skills

    def find_skill(self, name: str) -> SkillConfig | None:
        """Find a skill by exact name (case-insensitive)."""
        name_lower = name.lower()
        for skill in self.load_all():
            if skill.name.lower() == name_lower:
                return skill
        return None

    def get_system_prompt_section(self) -> str:
        """
        Build the system prompt section that describes available skills.
        Injected into LLM system prompt so the model knows what skills exist.
        """
        skills = self.load_all()
        if not skills:
            return ""

        lines: list[str] = [
            "",
            "## Available Skills",
            "You have access to the following skills. When the user invokes /skill <name>,",
            "the skill's instructions are prepended to your system context.",
            "",
        ]
        for s in skills:
            lines.append(f"- **{s.name}**: {s.description}")
            if s.when_to_use:
                lines.append(f"  When to use: {s.when_to_use}")
            if s.allowed_tools:
                lines.append(f"  Allowed tools: {', '.join(s.allowed_tools)}")
            if s.argument_hint:
                lines.append(f"  Usage: /skill {s.name} {s.argument_hint}")

        return "\n".join(lines)

    def ensure_skills_dir(self) -> None:
        """Create the skills directory if it doesn't exist."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def list_names(self) -> list[str]:
        """Return all skill names."""
        return [s.name for s in self.load_all()]
