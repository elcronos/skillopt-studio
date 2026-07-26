"""Register the ``generic_qa`` environment into the installed SkillOpt checkout.

SkillOpt discovers environments via ``scripts/train.py::_register_builtins()`` (and
the identical block in ``scripts/eval_only.py``), which lazily ``import``s each
adapter inside a ``try/except ImportError`` and stores it in ``_ENV_REGISTRY``
keyed by env name (verified from source). ``skillopt/envs/__init__.py`` is empty;
registration happens entirely in those scripts.

CHOSEN MECHANISM (most robust, recorded): two idempotent steps performed on the
cloned EDITABLE checkout (``<venv>/src/skillopt``):

1. **Vendor the adapter into the checkout** so a plain
   ``from skillopt.envs.generic_qa.adapter import GenericQAAdapter`` works:
   create ``skillopt/envs/generic_qa/{__init__.py, adapter.py}`` where
   ``adapter.py`` re-exports the studio's ``GenericQAEnv`` (it adds the studio
   ``skillopt_studio_envs`` dir to ``sys.path`` if needed, then imports it). This
   keeps the single source of truth in the studio package while satisfying
   SkillOpt's import path.
2. **Patch ``_register_builtins``** in ``scripts/train.py`` and
   ``scripts/eval_only.py`` by appending an idempotent ``try/except`` block that
   registers ``generic_qa``. The patch is marked with a sentinel comment so it is
   applied exactly once.

Rationale vs. alternatives:
- A ``sitecustomize`` injecting into ``_ENV_REGISTRY`` is fragile: ``_ENV_REGISTRY``
  is module-local to each script and ``_register_builtins`` repopulates it on every
  ``get_adapter`` call, so a one-time injection would be overwritten. Patching the
  registration function is therefore the reliable hook.
- Editing the checkout is safe because it is the studio's own pinned editable clone
  managed by ``run.sh``; the patch is idempotent and reversible (sentinel-guarded).

``self_test`` runs ``python scripts/train.py --config <generated> ...`` resolution
path (via importing the patched script's registry) to confirm ``generic_qa`` is
visible. Where the cloned checkout is absent (CI without install), functions
return a structured "skipped" result rather than raising.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .. import config

_SENTINEL = "# >>> skillopt-studio: generic_qa registration (idempotent) >>>"
_SENTINEL_END = "# <<< skillopt-studio: generic_qa registration <<<"

# The studio package dir that holds skillopt_studio_envs/generic_qa.
# repo_root/skillopt_studio_envs
_STUDIO_ENVS_DIR = config.REPO_ROOT / "skillopt_studio_envs"

_REGISTER_BLOCK = f'''
{_SENTINEL}
    try:
        from skillopt.envs.generic_qa.adapter import GenericQAAdapter
        _ENV_REGISTRY["generic_qa"] = GenericQAAdapter
    except ImportError:
        pass
{_SENTINEL_END}
'''

# adapter.py shim vendored into the cloned checkout's skillopt/envs/generic_qa/.
_ADAPTER_SHIM = f'''"""generic_qa adapter shim (installed by SkillOpt Studio).

Re-exports the studio's GenericQAEnv so SkillOpt can import it via the standard
``skillopt.envs.generic_qa.adapter`` path. The real implementation lives in the
studio package ``skillopt_studio_envs.generic_qa`` (single source of truth).
"""
from __future__ import annotations

import os
import sys

_STUDIO_ENVS_DIR = {str(_STUDIO_ENVS_DIR)!r}
if _STUDIO_ENVS_DIR not in sys.path and os.path.isdir(_STUDIO_ENVS_DIR):
    sys.path.insert(0, _STUDIO_ENVS_DIR)

from generic_qa.env import GenericQAEnv as GenericQAAdapter  # noqa: E402

__all__ = ["GenericQAAdapter"]
'''


def _clone_dir() -> Path:
    return Path(config.SKILLOPT_CLONE_DIR)


def _clone_sha(clone: Path) -> str | None:
    """Return the checked-out git SHA of *clone*, or None if not a git repo."""
    git_dir = clone / ".git"
    if not git_dir.exists():
        return None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(clone), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def assert_pinned_sha(clone: Path) -> None:
    """Assert the clone is checked out at the pinned SHA before patching.

    Fails LOUD (raises ``RuntimeError``) on mismatch so we never patch a drifted
    SkillOpt checkout (security #12). When the checkout has no git metadata (e.g.
    a tarball install) the check is skipped with no error — there is nothing to
    verify against.
    """
    sha = _clone_sha(clone)
    if sha is None:
        return
    pinned = config.SKILLOPT_PINNED_SHA
    if sha != pinned:
        raise RuntimeError(
            f"SkillOpt checkout SHA mismatch: clone at {clone} is {sha!r} but the "
            f"pinned SHA is {pinned!r}. Refusing to patch a drifted checkout."
        )


def vendor_adapter(clone_dir: str | Path | None = None) -> dict[str, Any]:
    """Create ``skillopt/envs/generic_qa/{__init__.py,adapter.py}`` in the checkout."""
    clone = Path(clone_dir) if clone_dir else _clone_dir()
    envs_dir = clone / "skillopt" / "envs"
    if not envs_dir.is_dir():
        return {"status": "skipped", "reason": f"skillopt checkout not found at {clone}"}

    pkg = envs_dir / "generic_qa"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        '"""generic_qa env package (installed by SkillOpt Studio)."""\n',
        encoding="utf-8",
    )
    (pkg / "adapter.py").write_text(_ADAPTER_SHIM, encoding="utf-8")
    return {"status": "ok", "path": str(pkg)}


def patch_register_builtins(clone_dir: str | Path | None = None) -> dict[str, Any]:
    """Idempotently append the generic_qa registration block to the registry
    functions in train.py and eval_only.py."""
    clone = Path(clone_dir) if clone_dir else _clone_dir()
    scripts_dir = clone / "scripts"
    if not scripts_dir.is_dir():
        return {"status": "skipped", "reason": f"scripts/ not found in checkout at {clone}"}

    # Fail loud before mutating a drifted checkout (security #12).
    assert_pinned_sha(clone)

    patched: list[str] = []
    already: list[str] = []
    for name in ("train.py", "eval_only.py"):
        path = scripts_dir / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if _SENTINEL in text:
            already.append(name)
            continue
        new_text = _insert_block(text)
        if new_text is None:
            return {"status": "error", "reason": f"could not locate _register_builtins body in {name}"}
        # Back up once.
        backup = path.with_suffix(path.suffix + ".studio-bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        patched.append(name)

    if not patched and not already:
        return {"status": "error", "reason": "neither train.py nor eval_only.py found"}
    return {"status": "ok", "patched": patched, "already_patched": already}


def _insert_block(text: str) -> str | None:
    """Insert the registration block at the END of the ``_register_builtins``
    function body. Returns the new text, or None if the function is not found.

    Strategy: find ``def _register_builtins(`` then insert the block immediately
    before the first top-level ``def `` / ``class `` that follows it (i.e. the
    next module-level statement), preserving indentation inside the function.
    """
    marker = "def _register_builtins("
    idx = text.find(marker)
    if idx == -1:
        return None
    # Find the end of the function: the next line that starts at column 0 with
    # 'def ' or 'class ' AFTER the function signature.
    rest_start = text.index("\n", idx) + 1
    lines = text[rest_start:].splitlines(keepends=True)
    insert_at_line = None
    for i, line in enumerate(lines):
        if i == 0:
            continue
        if line and not line[0].isspace() and (line.startswith("def ") or line.startswith("class ") or line.startswith("#") or line.strip().startswith("get_adapter")):
            insert_at_line = i
            break
    if insert_at_line is None:
        # Insert at end of file body for the function (fallback).
        insert_at_line = len(lines)
    head = "".join(lines[:insert_at_line]).rstrip("\n")
    tail = "".join(lines[insert_at_line:])
    block = _REGISTER_BLOCK.rstrip("\n")
    rebuilt = text[:rest_start] + head + "\n" + block + "\n\n\n" + tail
    return rebuilt


def register(clone_dir: str | Path | None = None) -> dict[str, Any]:
    """Perform both registration steps. Idempotent. Returns a combined report."""
    vendored = vendor_adapter(clone_dir)
    patched = patch_register_builtins(clone_dir)
    status = "ok" if vendored.get("status") in ("ok", "skipped") and patched.get("status") in ("ok", "skipped") else "error"
    if vendored.get("status") == "skipped" or patched.get("status") == "skipped":
        status = "skipped"
    return {"status": status, "vendor": vendored, "patch": patched}


def self_test(clone_dir: str | Path | None = None) -> dict[str, Any]:
    """Confirm SkillOpt's registry resolves ``generic_qa`` after registration.

    Imports the (patched) ``scripts.train`` module from the checkout, calls
    ``_register_builtins``, and checks ``generic_qa`` is in ``_ENV_REGISTRY``.
    Returns ``{"status": "pass"|"fail"|"skipped", ...}`` — never raises.
    """
    import importlib.util
    import sys

    clone = Path(clone_dir) if clone_dir else _clone_dir()
    train_py = clone / "scripts" / "train.py"
    if not train_py.is_file():
        return {"status": "skipped", "reason": f"no train.py at {train_py}"}

    # Ensure the checkout root and studio envs are importable.
    for p in (str(clone), str(_STUDIO_ENVS_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)

    try:
        spec = importlib.util.spec_from_file_location("_studio_train_probe", str(train_py))
        if spec is None or spec.loader is None:
            return {"status": "fail", "reason": "could not load train.py spec"}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        register_fn = getattr(mod, "_register_builtins", None)
        registry = getattr(mod, "_ENV_REGISTRY", None)
        if register_fn is None or registry is None:
            return {"status": "fail", "reason": "train.py missing _register_builtins/_ENV_REGISTRY"}
        register_fn()
        ok = "generic_qa" in registry
        return {
            "status": "pass" if ok else "fail",
            "registered_envs": sorted(registry.keys()),
            "generic_qa_present": ok,
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "reason": f"{type(exc).__name__}: {exc}"}


__all__ = [
    "vendor_adapter",
    "patch_register_builtins",
    "assert_pinned_sha",
    "register",
    "self_test",
]
