"""Secret storage for SkillOpt Studio.

``store`` persists provider API keys (OS keyring primary, chmod-600 JSON
fallback) keyed by ``(backend, role)``; ``scrub`` strips all known secret vars
from an environment before it is handed to an untrusted custom-scorer subprocess.
Key values are never logged or returned by metadata APIs.
"""

from .scrub import scrub_env, is_secret_var
from .store import set_key, get_key, delete_key, has_key, list_keys

__all__ = [
    "scrub_env",
    "is_secret_var",
    "set_key",
    "get_key",
    "delete_key",
    "has_key",
    "list_keys",
]
