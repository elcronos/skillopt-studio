"""Base protocol for provider adapters.

Each adapter implements ``ProviderAdapter`` — a runtime-checkable Protocol
so adapters can be duck-typed without requiring explicit subclassing.

Behavioural contract:
- ``root_paths()`` returns the directories this adapter will search.
- ``scan()`` returns a (possibly empty) list of ``Skill`` objects.
- ``scan()`` must NEVER raise: missing roots, permission errors, or unexpected
  file contents must be caught and degraded to an empty or partial result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain import Skill, ProviderName


@runtime_checkable
class ProviderAdapter(Protocol):
    """Protocol that all scanner adapters must satisfy."""

    @property
    def provider_name(self) -> ProviderName:
        """The provider this adapter represents."""
        ...

    def root_paths(self) -> list[Path]:
        """Return the filesystem roots this adapter searches.

        Missing paths must be included silently — callers use this list for
        diagnostics/display, not for existence checks.
        """
        ...

    def scan(self) -> list[Skill]:
        """Discover and return skills from all root paths.

        Must be fully graceful: always returns a list (possibly empty), never
        raises regardless of filesystem state.
        """
        ...


__all__ = ["ProviderAdapter"]
