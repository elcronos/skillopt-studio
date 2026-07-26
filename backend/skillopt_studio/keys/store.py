"""Secret storage: OS keyring primary, chmod-600 JSON fallback.

Keys are stored per ``(backend, role)`` pair (role is typically ``optimizer`` or
``target``). The OS keyring (macOS Keychain via the ``keyring`` package) is the
primary store; when no usable keyring backend is available we fall back to a
``.keys.json`` file written with ``0600`` permissions and gitignored.

Hard rules:
- Key VALUES are never logged. Only key NAMES / presence may be logged.
- ``list_keys`` / metadata APIs never return values.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from .. import config

logger = logging.getLogger("skillopt_studio.keys")

# Keyring service namespace. Keyring "username" is the ``backend/role`` key.
_SERVICE = "skillopt-studio"

# Fallback file (gitignored — see .gitignore ``.keys.json``).
_FALLBACK_PATH: Path = config.REPO_ROOT / ".keys.json"


def _keyring():
    """Return the ``keyring`` module if it has a usable backend, else None."""
    try:
        import keyring  # noqa: PLC0415 - optional/lazy import
        from keyring.backends.fail import Keyring as FailKeyring  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - keyring missing or import error
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001
        return None
    if isinstance(backend, FailKeyring):
        # The "fail" backend raises on every op; treat as unavailable.
        return None
    return keyring


def _entry_key(backend: str, role: str) -> str:
    """Compose the stable storage key from ``backend`` and ``role``."""
    return f"{backend}/{role}"


# --- fallback file helpers ---------------------------------------------------
def _read_fallback() -> dict[str, str]:
    if not _FALLBACK_PATH.exists():
        return {}
    try:
        with _FALLBACK_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - corrupt/partial file degrades to empty
        logger.warning("fallback key file unreadable; treating as empty")
        return {}


def _write_fallback(data: dict[str, str]) -> None:
    # Write then chmod 600 so the file is never briefly world-readable with data.
    tmp = _FALLBACK_PATH.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
    finally:
        pass
    os.chmod(tmp, 0o600)
    os.replace(tmp, _FALLBACK_PATH)
    os.chmod(_FALLBACK_PATH, 0o600)


# --- public API --------------------------------------------------------------
def set_key(backend: str, role: str, value: str) -> str:
    """Store ``value`` for ``(backend, role)``. Returns the storage mechanism used.

    Mechanism is ``"keyring"`` or ``"file"``. The value is never logged.
    """
    key = _entry_key(backend, role)
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(_SERVICE, key, value)
            logger.info("stored key for %s via keyring", key)
            return "keyring"
        except Exception:  # noqa: BLE001 - fall back to file on any keyring error
            logger.warning("keyring set failed for %s; using file fallback", key)
    data = _read_fallback()
    data[key] = value
    _write_fallback(data)
    logger.info("stored key for %s via file fallback", key)
    return "file"


def get_key(backend: str, role: str) -> Optional[str]:
    """Return the stored secret for ``(backend, role)``, or None if absent."""
    key = _entry_key(backend, role)
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(_SERVICE, key)
            if value is not None:
                return value
        except Exception:  # noqa: BLE001
            logger.warning("keyring get failed for %s; checking file fallback", key)
    return _read_fallback().get(key)


def delete_key(backend: str, role: str) -> bool:
    """Delete the secret for ``(backend, role)``. Returns True if anything was removed."""
    key = _entry_key(backend, role)
    removed = False
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(_SERVICE, key)
            removed = True
        except Exception:  # noqa: BLE001 - not present in keyring is fine
            pass
    data = _read_fallback()
    if key in data:
        del data[key]
        _write_fallback(data)
        removed = True
    if removed:
        logger.info("deleted key for %s", key)
    return removed


def has_key(backend: str, role: str) -> bool:
    """Return True when a secret exists for ``(backend, role)`` (no value exposed)."""
    return get_key(backend, role) is not None


def list_keys() -> list[str]:
    """Return the ``backend/role`` identifiers known to the file fallback.

    Never returns values. The OS keyring is not enumerable per-service in a
    portable way, so this lists fallback entries only — used for diagnostics.
    """
    return sorted(_read_fallback().keys())


__all__ = ["set_key", "get_key", "delete_key", "has_key", "list_keys"]
