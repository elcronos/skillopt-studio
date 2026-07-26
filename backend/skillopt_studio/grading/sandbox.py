"""Honest-mistake containment sandbox for user Python scorers.

THREAT MODEL (read this before changing anything):
    This sandbox provides HONEST-MISTAKE CONTAINMENT, NOT adversarial isolation.
    It protects against a well-meaning user scorer that loops forever, allocates
    too much memory, prints garbage, or accidentally reads an API key from the
    environment. It does NOT defend against a deliberately malicious scorer:
    a determined attacker with arbitrary Python can still escape ``resource``
    limits, touch the filesystem outside the temp cwd, or open network sockets.
    Running custom scorers therefore requires explicit user CONSENT
    (``GraderConfig.custom_consent``); the API surface must refuse otherwise.

Mechanisms:
    - CHILD PROCESS via ``subprocess`` with an argv LIST (never ``shell=True``).
    - ``resource`` rlimits applied in a preexec hook: CPU seconds, address space,
      file size, and (where supported) process count. On macOS several limits
      are ADVISORY / unsupported (notably ``RLIMIT_AS`` is frequently ignored by
      the Darwin kernel and ``RLIMIT_NPROC`` may not be enforced) — documented
      here and degraded gracefully (a failed ``setrlimit`` is ignored).
    - WALL-CLOCK timeout (default 60s) enforced by the parent; on timeout the
      whole process group is killed.
    - TEMP CWD: a throwaway directory is the child's working directory.
    - ENV SCRUBBED of every known API-key var (see ``keys.scrub``) plus reduced
      to a minimal allowlist so the scorer cannot read provider credentials.
    - SCORE clamped to ``[0, 1]`` by the caller (custom.py).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Optional

from ..keys.scrub import scrub_env

logger = logging.getLogger("skillopt_studio.grading.sandbox")

DEFAULT_TIMEOUT_SECONDS = 60

# Advisory resource limits. On macOS RLIMIT_AS / RLIMIT_NPROC are often not
# enforced by the kernel; we still attempt them and ignore failures.
_CPU_SECONDS = 30
_ADDRESS_SPACE_BYTES = 1024 * 1024 * 1024  # 1 GiB (advisory on macOS)
_FILE_SIZE_BYTES = 16 * 1024 * 1024  # 16 MiB output file cap


def _apply_rlimits() -> None:  # pragma: no cover - runs in the child process
    """preexec hook: start a new session + apply best-effort rlimits.

    Every ``setrlimit`` is wrapped: an unsupported limit (common on macOS) is
    ignored rather than aborting the child.
    """
    try:
        os.setsid()
    except Exception:  # noqa: BLE001
        pass
    try:
        import resource
    except Exception:  # noqa: BLE001 - resource unavailable: nothing to enforce
        return
    for name, soft in (
        ("RLIMIT_CPU", _CPU_SECONDS),
        ("RLIMIT_AS", _ADDRESS_SPACE_BYTES),
        ("RLIMIT_FSIZE", _FILE_SIZE_BYTES),
        ("RLIMIT_NPROC", 64),
    ):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (soft, soft))
        except Exception:  # noqa: BLE001 - advisory: ignore unsupported limits
            pass


def _minimal_env() -> dict[str, str]:
    """A scrubbed, minimal environment for the child process."""
    base = scrub_env(dict(os.environ))
    allow = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "HOME"}
    env = {k: v for k, v in base.items() if k in allow}
    env.setdefault("PATH", "/usr/bin:/bin")
    env["PYTHONUNBUFFERED"] = "1"
    # Defense in depth: discourage importing site/user packages with creds.
    env["PYTHONNOUSERSITE"] = "1"
    return env


def run_scorer(
    runner_path: str,
    payload: dict,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    python_executable: Optional[str] = None,
) -> dict:
    """Run ``runner_path`` as a child process, feeding ``payload`` as JSON on stdin.

    The child is expected to print a single JSON object ``{"score": <float>}`` to
    stdout. Returns a dict ``{"ok": bool, "score": float|None, "error": str|None,
    "timed_out": bool}``. Never raises; all failure modes are reported in the dict.

    Security: argv is a LIST, ``shell=False``, env is scrubbed + minimized, cwd is
    a throwaway temp dir, and a wall-clock timeout kills the whole process group.
    """
    python_executable = python_executable or sys.executable
    argv = [python_executable, "-I", runner_path]
    env = _minimal_env()

    with tempfile.TemporaryDirectory(prefix="skillopt-scorer-") as tmpdir:
        try:
            proc = subprocess.run(
                argv,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
                env=env,
                shell=False,
                preexec_fn=_apply_rlimits,
                start_new_session=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("custom scorer timed out after %ss", timeout)
            return {"ok": False, "score": None, "error": "timeout", "timed_out": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "score": None, "error": str(exc), "timed_out": False}

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[-500:]
        return {"ok": False, "score": None, "error": err or "non-zero exit", "timed_out": False}

    out = (proc.stdout or "").strip()
    try:
        # Take the last JSON line so incidental prints before the result are tolerated.
        last = out.splitlines()[-1] if out else ""
        result = json.loads(last)
        score = float(result["score"])
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "score": None,
            "error": f"could not parse scorer output: {exc}",
            "timed_out": False,
        }
    return {"ok": True, "score": score, "error": None, "timed_out": False}


__all__ = ["run_scorer", "DEFAULT_TIMEOUT_SECONDS"]
