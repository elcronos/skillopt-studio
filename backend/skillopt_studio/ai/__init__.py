"""AI-generation helpers backed by the local ``claude`` CLI.

This package drafts dataset cases, G-Eval criteria, and custom-Python scorers
from a skill body + a short user instruction. Output is always DRAFTED into the
existing editors for the user to review before saving — nothing is auto-applied
and generated custom scorer code is NEVER executed here (it travels into the
existing honest-mistake sandbox only on an explicit, consented run).
"""

from __future__ import annotations

from .claude_cli import (
    ClaudeCLIError,
    claude_available,
    generate_custom_scorer,
    generate_dataset_cases,
    generate_geval_criteria,
)

__all__ = [
    "ClaudeCLIError",
    "claude_available",
    "generate_dataset_cases",
    "generate_geval_criteria",
    "generate_custom_scorer",
]
