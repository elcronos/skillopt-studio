"""CWD (current working directory) provider adapter.

Scans the current working directory for skill Markdown files.  Recognised
filenames (case-insensitive):
- ``SKILL.md``
- ``skill.md``
- Any ``*.skill.md`` pattern (e.g. ``my-tool.skill.md``)

The scan is shallow-first (direct children) but also recurses one level into
obvious skill-container subdirectories named ``skills/`` or ``.skills/``.

Each discovered file becomes one Skill with:
- ``name``: frontmatter ``name`` field if present, else the filename stem.
- ``body``: full file content.
- ``provider``: ``ProviderName.cwd``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from ..domain import ProviderName, Skill

logger = logging.getLogger("skillopt_studio.scanner.cwd")

_FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n\s*---\s*\n?(.*)", re.DOTALL)


def _parse_name_from_frontmatter(text: str) -> Optional[str]:
    """Extract the ``name`` field from YAML frontmatter, if present."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.startswith("name"):
            _, _, val = line.partition(":")
            stripped = val.strip().strip('"').strip("'")
            if stripped:
                return stripped
    return None


def _stable_id(source_path: Path) -> str:
    digest = hashlib.sha1(str(source_path).encode()).hexdigest()[:12]
    return f"cwd:{digest}"


def _is_skill_file(path: Path) -> bool:
    """Return True when the filename matches a skill markdown pattern."""
    name_lower = path.name.lower()
    return name_lower == "skill.md" or name_lower.endswith(".skill.md")


def _skill_from_path(skill_md: Path) -> Optional[Skill]:
    """Parse a skill markdown file and return a Skill, or None on failure."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("cwd: cannot read %s: %s", skill_md, exc)
        return None

    name = _parse_name_from_frontmatter(text) or skill_md.stem

    return Skill(
        id=_stable_id(skill_md),
        name=name,
        provider=ProviderName.cwd,
        source_path=str(skill_md.resolve()),
        body=text,
    )


class CwdAdapter:
    """Adapter that scans the current working directory for skill files.

    Args:
        cwd: The directory to scan.
    """

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.cwd

    def root_paths(self) -> list[Path]:
        return [self._cwd]

    def scan(self) -> list[Skill]:
        skills: list[Skill] = []
        seen: set[str] = set()

        if not self._cwd.exists():
            return skills

        def _add(p: Path) -> None:
            resolved = str(p.resolve())
            if resolved in seen:
                return
            seen.add(resolved)
            s = _skill_from_path(p)
            if s:
                skills.append(s)

        # Shallow scan of cwd for SKILL.md / *.skill.md
        try:
            for p in self._cwd.iterdir():
                if p.is_file() and _is_skill_file(p):
                    _add(p)
                elif p.is_dir() and p.name.lower() in ("skills", ".skills"):
                    # One level into recognised skill container dirs
                    try:
                        for child in p.iterdir():
                            if child.is_file() and _is_skill_file(child):
                                _add(child)
                            elif child.is_dir():
                                # skills/<name>/SKILL.md pattern
                                nested = child / "SKILL.md"
                                if nested.is_file():
                                    _add(nested)
                    except OSError as exc:
                        logger.debug("cwd: error iterating %s: %s", p, exc)
        except OSError as exc:
            logger.debug("cwd: error iterating %s: %s", self._cwd, exc)

        return skills


__all__ = ["CwdAdapter"]
