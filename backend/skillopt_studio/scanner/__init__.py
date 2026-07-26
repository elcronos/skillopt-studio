"""Multi-provider skill scanner package.

Exports the top-level ``scan_all`` entry-point via the registry.
"""

from .registry import scan_all  # noqa: F401

__all__ = ["scan_all"]
