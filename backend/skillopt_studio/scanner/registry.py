"""Aggregate registry: runs all adapters and deduplicates results.

``scan_all(cwd)`` is the single entry-point used by the API router.  It
instantiates every adapter, collects their results, deduplicates on
``source_path`` (since the same file might be found by multiple adapters in
edge cases), and returns a stable list sorted by ``(provider, name)``.

Stable IDs are guaranteed within a single ``scan_all`` call because each
adapter derives its ID from a SHA-1 of the resolved ``source_path``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..domain import Skill
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .cwd import CwdAdapter
from .openai import OpenAIAdapter

logger = logging.getLogger("skillopt_studio.scanner.registry")


def scan_all(cwd: Path) -> list[Skill]:
    """Scan all providers and return a deduplicated, sorted list of skills.

    Args:
        cwd: The current working directory; passed to adapters that need it
             (codex, openai, cwd).

    Returns:
        A list of ``Skill`` objects.  Never raises — individual adapter errors
        are logged at DEBUG level and produce empty contributions.
    """
    adapters = [
        ClaudeAdapter(),
        CodexAdapter(cwd),
        OpenAIAdapter(cwd),
        CwdAdapter(cwd),
    ]

    seen_paths: set[str] = set()
    skills: list[Skill] = []

    for adapter in adapters:
        try:
            results = adapter.scan()
        except Exception:  # noqa: BLE001 - belt-and-suspenders; adapters should not raise
            logger.exception(
                "scanner: adapter %s raised unexpectedly; skipping",
                adapter.provider_name,
            )
            results = []

        for skill in results:
            if skill.source_path in seen_paths:
                logger.debug(
                    "scanner: duplicate source_path %s from %s; skipping",
                    skill.source_path,
                    adapter.provider_name,
                )
                continue
            seen_paths.add(skill.source_path)
            skills.append(skill)

    # Stable sort: provider then name (case-insensitive)
    skills.sort(key=lambda s: (s.provider.value, s.name.lower()))
    return skills


__all__ = ["scan_all"]
