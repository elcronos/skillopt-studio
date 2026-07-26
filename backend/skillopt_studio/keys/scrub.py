"""Environment scrubbing for untrusted subprocesses.

``scrub_env`` removes every known API-key / secret variable from a copied
environment mapping so that a user-supplied custom Python scorer (run in the
honest-mistake sandbox) cannot read provider credentials. Scrubbing is
defensive on two axes:

- an explicit allowlist of known SkillOpt backend secret vars, and
- prefix/substring heuristics catching ``*_API_KEY``, ``*_SECRET``, ``*_TOKEN``,
  and per-role overrides (``OPTIMIZER_*`` / ``TARGET_*``).

Key VALUES are never logged anywhere in this module.
"""

from __future__ import annotations

# Explicit secret variables from the verified SkillOpt backend contract
# (SKILLOPT_INTEGRATION.md "Keys / backends"). Per-role variants
# (``OPTIMIZER_*`` / ``TARGET_*``) are also covered by the heuristics below.
_KNOWN_SECRET_VARS: frozenset[str] = frozenset(
    {
        # Azure OpenAI (openai_chat / openai_compatible)
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_AUTH_MODE",
        # Anthropic (claude_chat)
        "ANTHROPIC_API_KEY",
        # OpenAI (openai_compatible / api.openai.com)
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
        # Qwen (qwen_chat)
        "QWEN_CHAT_BASE_URL",
        "QWEN_CHAT_MODEL",
        "QWEN_API_KEY",
        # Minimax (minimax_chat)
        "MINIMAX_BASE_URL",
        "MINIMAX_API_KEY",
        "MINIMAX_MODEL",
    }
)

# Substrings that mark a variable as a secret regardless of its concrete name.
_SECRET_SUBSTRINGS: tuple[str, ...] = (
    "API_KEY",
    "APIKEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "ACCESS_KEY",
)

# Prefixes for vars that proxy any of the above onto a specific role. We drop the
# whole role-prefixed namespace to be safe (e.g. ``OPTIMIZER_AZURE_OPENAI_*``).
_SECRET_PREFIXES: tuple[str, ...] = (
    "AZURE_OPENAI_",
    "OPTIMIZER_",
    "TARGET_",
    "OPENAI_",
    "QWEN_",
    "MINIMAX_",
    "ANTHROPIC_",
)


def is_secret_var(name: str) -> bool:
    """Return True when ``name`` should be removed from an untrusted env."""
    upper = name.upper()
    if upper in _KNOWN_SECRET_VARS:
        return True
    if any(sub in upper for sub in _SECRET_SUBSTRINGS):
        return True
    if any(upper.startswith(prefix) for prefix in _SECRET_PREFIXES):
        return True
    return False


def scrub_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``env`` with all known API-key / secret vars removed.

    The input mapping is never mutated. Variable names that are removed are not
    logged; values are never logged.
    """
    return {k: v for k, v in env.items() if not is_secret_var(k)}


__all__ = ["scrub_env", "is_secret_var"]
