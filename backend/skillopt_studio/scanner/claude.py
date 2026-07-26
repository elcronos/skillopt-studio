"""Claude provider adapter.

Scans two locations for skills:
1. ``~/.claude/skills/<skill-name>/SKILL.md`` — user-installed skills.
2. ``~/.claude/plugins/cache/**/<skill-name>/SKILL.md`` — plugin cache entries.

Each SKILL.md may have a YAML frontmatter block delimited by ``---``.  The
``name`` and ``description`` fields are extracted when present; the file body
(everything after the closing ``---``) is stored in ``Skill.body``.  Parsing
failures are silently degraded to a name derived from the directory.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from ..domain import ProviderName, Skill

logger = logging.getLogger("skillopt_studio.scanner.claude")

_HOME = Path.home()
_SKILLS_DIR = _HOME / ".claude" / "skills"
_PLUGIN_CACHE_DIR = _HOME / ".claude" / "plugins" / "cache"

# Regex to extract frontmatter: optional BOM, then --- ... --- block.
_FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n\s*---\s*\n?(.*)", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter_dict, body).  Never raises."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_fm, body = m.group(1), m.group(2)
    fm: dict[str, str] = {}
    for line in raw_fm.splitlines():
        # Simple key: value parsing — no nested YAML.
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm, body


def _stable_id(source_path: Path) -> str:
    """Return a stable short id from the source path hash."""
    digest = hashlib.sha1(str(source_path).encode()).hexdigest()[:12]
    return f"claude:{digest}"


def _skill_from_path(skill_md: Path) -> Optional[Skill]:
    """Parse a SKILL.md and return a Skill, or None on failure."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("claude: cannot read %s: %s", skill_md, exc)
        return None

    fm, body = _parse_frontmatter(text)
    name = fm.get("name") or skill_md.parent.name
    description = fm.get("description", "")
    full_body = text  # keep full file as body (frontmatter + content)

    return Skill(
        id=_stable_id(skill_md),
        name=name,
        provider=ProviderName.claude,
        source_path=str(skill_md.resolve()),
        body=full_body,
    )


class ClaudeAdapter:
    """Adapter that scans Claude skill directories."""

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.claude

    def root_paths(self) -> list[Path]:
        return [_SKILLS_DIR, _PLUGIN_CACHE_DIR]

    def scan(self) -> list[Skill]:
        skills: list[Skill] = []

        # 1. ~/.claude/skills/<name>/SKILL.md
        if _SKILLS_DIR.exists():
            try:
                for skill_dir in _SKILLS_DIR.iterdir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.is_file():
                        s = _skill_from_path(skill_md)
                        if s:
                            skills.append(s)
            except OSError as exc:
                logger.debug("claude: error iterating %s: %s", _SKILLS_DIR, exc)

        # 2. ~/.claude/plugins/cache/**/<skill-dir>/SKILL.md (any depth)
        if _PLUGIN_CACHE_DIR.exists():
            try:
                for skill_md in _PLUGIN_CACHE_DIR.rglob("SKILL.md"):
                    s = _skill_from_path(skill_md)
                    if s:
                        skills.append(s)
            except OSError as exc:
                logger.debug("claude: error globbing %s: %s", _PLUGIN_CACHE_DIR, exc)

        return skills


__all__ = ["ClaudeAdapter"]
