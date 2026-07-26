"""OpenAI provider adapter.

Heuristic scan for OpenAI assistant configuration files.  There is no single
canonical location for OpenAI assistant configs, so this adapter applies a
best-effort search across plausible locations:

1. ``~/.openai/`` — home-directory config dir (analogous to ~/.codex).
2. ``<cwd>/openai/`` and ``<cwd>/.openai/`` — project-local config dirs.
3. Any ``*.json`` file in ``<cwd>`` whose path component contains "openai"
   or "assistant" (e.g. ``openai_assistant.json``, ``assistant_config.json``).

Each discovered JSON file is read and a Skill is created with:
- ``name``: the ``name`` field from the JSON, or the filename stem.
- ``body``: the raw JSON text (for inspection/optimization).
- ``provider``: ``ProviderName.openai``.

If no JSON files are found anywhere, the adapter returns an empty list — this
is the expected behaviour when OpenAI assistant configs are absent.

Degrades gracefully: JSON parse errors, permission errors, and missing dirs
all result in the file being skipped, never a raised exception.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from ..domain import ProviderName, Skill

logger = logging.getLogger("skillopt_studio.scanner.openai")

_HOME = Path.home()
_OPENAI_HOME = _HOME / ".openai"


def _stable_id(source_path: Path) -> str:
    digest = hashlib.sha1(str(source_path).encode()).hexdigest()[:12]
    return f"openai:{digest}"


def _skill_from_json(json_path: Path) -> Optional[Skill]:
    """Parse an OpenAI assistant JSON file and return a Skill, or None."""
    try:
        text = json_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("openai: cannot read %s: %s", json_path, exc)
        return None

    # Try to extract a name from the JSON; fall back to filename stem.
    name = json_path.stem
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            name = str(data.get("name") or data.get("assistant_name") or name)
    except json.JSONDecodeError:
        pass  # Use filename stem as name

    return Skill(
        id=_stable_id(json_path),
        name=name,
        provider=ProviderName.openai,
        source_path=str(json_path.resolve()),
        body=text,
    )


def _is_assistant_json(path: Path) -> bool:
    """Return True when the path looks like an OpenAI assistant config."""
    lowered = path.name.lower()
    return (
        path.suffix == ".json"
        and any(kw in lowered for kw in ("openai", "assistant", "gpt"))
    )


class OpenAIAdapter:
    """Adapter that scans for OpenAI assistant configuration files.

    Heuristic — degrades gracefully to an empty list when no configs exist.

    Args:
        cwd: The current working directory to include in the search.
    """

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.openai

    def root_paths(self) -> list[Path]:
        roots = [
            _OPENAI_HOME,
            self._cwd / "openai",
            self._cwd / ".openai",
        ]
        return roots

    def scan(self) -> list[Skill]:
        skills: list[Skill] = []
        seen: set[str] = set()

        def _add(p: Path) -> None:
            resolved = str(p.resolve())
            if resolved in seen:
                return
            seen.add(resolved)
            s = _skill_from_json(p)
            if s:
                skills.append(s)

        # 1. ~/.openai/ (any JSON within)
        if _OPENAI_HOME.exists():
            try:
                for p in _OPENAI_HOME.rglob("*.json"):
                    _add(p)
            except OSError as exc:
                logger.debug("openai: error scanning %s: %s", _OPENAI_HOME, exc)

        # 2. <cwd>/openai/ and <cwd>/.openai/ subdirectories
        for subdir in (self._cwd / "openai", self._cwd / ".openai"):
            if subdir.exists():
                try:
                    for p in subdir.rglob("*.json"):
                        _add(p)
                except OSError as exc:
                    logger.debug("openai: error scanning %s: %s", subdir, exc)

        # 3. Heuristic: assistant-looking JSON files directly in cwd
        if self._cwd.exists():
            try:
                for p in self._cwd.glob("*.json"):
                    if _is_assistant_json(p):
                        _add(p)
            except OSError as exc:
                logger.debug("openai: error scanning cwd %s: %s", self._cwd, exc)

        return skills


__all__ = ["OpenAIAdapter"]
