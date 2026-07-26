"""Codex provider adapter.

Scans for Codex ``AGENTS.md`` files.  Two roots are searched:
1. The current working directory (``cwd``) passed to ``scan(cwd)``.
   For this adapter ``root_paths()`` returns a placeholder; the actual cwd
   is supplied at scan time via the class constructor.
2. ``~/.codex/`` (if it exists).

Each discovered ``AGENTS.md`` file becomes one ``Skill``.  The skill name is
derived from the first heading in the file or, failing that, from the
containing directory name.  The full file content is stored as ``body``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from ..domain import ProviderName, Skill

logger = logging.getLogger("skillopt_studio.scanner.codex")

_HOME = Path.home()
_CODEX_HOME = _HOME / ".codex"

_H1_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)


def _stable_id(source_path: Path) -> str:
    digest = hashlib.sha1(str(source_path).encode()).hexdigest()[:12]
    return f"codex:{digest}"


def _name_from_content(text: str, fallback: str) -> str:
    """Extract the first # heading from file text, or use fallback."""
    m = _H1_RE.search(text)
    if m:
        return m.group(1).strip()
    return fallback


def _skill_from_agents_md(agents_md: Path) -> Optional[Skill]:
    """Parse an AGENTS.md and return a Skill, or None on failure."""
    try:
        text = agents_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("codex: cannot read %s: %s", agents_md, exc)
        return None

    fallback_name = agents_md.parent.name or agents_md.name
    name = _name_from_content(text, fallback_name)

    return Skill(
        id=_stable_id(agents_md),
        name=name,
        provider=ProviderName.codex,
        source_path=str(agents_md.resolve()),
        body=text,
    )


class CodexAdapter:
    """Adapter that scans for Codex AGENTS.md files.

    Args:
        cwd: The current working directory to scan in addition to ~/.codex.
    """

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.codex

    def root_paths(self) -> list[Path]:
        roots = [self._cwd]
        if _CODEX_HOME.exists():
            roots.append(_CODEX_HOME)
        return roots

    def scan(self) -> list[Skill]:
        skills: list[Skill] = []
        seen: set[str] = set()

        roots: list[Path] = [self._cwd]
        if _CODEX_HOME.exists():
            roots.append(_CODEX_HOME)

        for root in roots:
            if not root.exists():
                continue
            try:
                for agents_md in root.rglob("AGENTS.md"):
                    resolved = str(agents_md.resolve())
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    s = _skill_from_agents_md(agents_md)
                    if s:
                        skills.append(s)
            except OSError as exc:
                logger.debug("codex: error scanning %s: %s", root, exc)

        return skills


__all__ = ["CodexAdapter"]
