"""Staged subprocess pipeline: SKILL.md -> runnable dist/<skill>/ LangGraph.

Runs the companion ``skill-to-langgraph`` scripts (in their own venv) as an
ordered list of stages, streaming each stage's stdout onto an event callback and
recording a per-stage result. A stage that exits non-zero aborts the pipeline
(remaining stages are skipped) and the terminal :class:`DoneEvent` reports the
failed status.

Stages (in order):
  1. extract   — extract_graphspec.py: SKILL.md -> graphspec.json (the LLM step)
  2. validate  — validate_graph.py: 6 deterministic checks + offline smoke
  3. gen_evals — gen_evals.py: emit pytest evals
  4. pytest    — run the generated evals
  5. package   — package_standalone.py: emit the portable dist/<skill>/ folder
  6. parity    — (optional) parity_run.py: live GEval skill-vs-graph parity
  7. improve   — self_improve.py: re-consolidate the pattern memory

Billing safety (verified design decision): the ``claude -p`` backend bills the
logged-in subscription, BUT if ``ANTHROPIC_API_KEY``/``OPENAI_API_KEY`` is present
in the environment the CLI silently switches to per-token API billing. So the env
is built EXPLICITLY per ``llm_backend``: ``"claude_cli"`` (default) SCRUBS those
keys so the subscription is used; ``"api"`` passes them through on purpose.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .. import config
from ..domain import DoneEvent, ErrorEvent, LogEvent, SSEEvent, StageEvent, TrainRunStatus

EventCallback = Callable[[SSEEvent], None]

# Env vars whose presence flips `claude -p` from subscription to API billing.
_API_KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


class LangGraphUnavailable(RuntimeError):
    """The companion skill-to-langgraph repo or its venv could not be found."""


@dataclass
class StageResult:
    name: str
    ok: bool = False
    exit_code: Optional[int] = None
    skipped: bool = False
    tail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "skipped": self.skipped,
            "tail": self.tail,
        }


class ConversionHandle:
    """Live handle to the in-flight stage's subprocess; supports cancellation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self.cancelled = False

    def _set_proc(self, proc: Optional[subprocess.Popen]) -> None:
        with self._lock:
            self._proc = proc

    def cancel(self) -> bool:
        """SIGTERM the current stage's process group; stop launching further stages."""
        with self._lock:
            self.cancelled = True
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return False
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                try:
                    proc.terminate()
                except OSError:
                    return False
            return True


# ── env / availability ───────────────────────────────────────────────────────
def ensure_available() -> tuple[Path, Path]:
    """Return (skill_dir, venv_python) or raise LangGraphUnavailable."""
    skill_dir = config.LANGGRAPH_SKILL_DIR
    if not (skill_dir / "scripts" / "extract_graphspec.py").is_file():
        raise LangGraphUnavailable(
            f"skill-to-langgraph not found at {skill_dir} "
            f"(set SKILLOPT_LANGGRAPH_DIR to its checkout)"
        )
    py = config.LANGGRAPH_VENV_PYTHON
    if not py.exists():
        raise LangGraphUnavailable(
            f"skill-to-langgraph venv missing at {py}. Build it: "
            f"cd {skill_dir} && python3.12 -m venv .venv && "
            f".venv/bin/pip install -r requirements.txt"
        )
    return skill_dir, py


def build_env(llm_backend: str) -> dict[str, str]:
    """Build the subprocess env, controlling LLM billing explicitly.

    ``claude_cli`` (default): scrub API keys so `claude -p` uses the subscription.
    ``api``: keep API keys so the SDK/CLI bills per token on purpose.
    """
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    if llm_backend != "api":
        for var in _API_KEY_VARS:
            env.pop(var, None)
    return env


# ── stage argv ───────────────────────────────────────────────────────────────
def _spec_path(skill_dir: Path, skill: str) -> Path:
    return skill_dir / "training" / "specs" / f"{skill}.graphspec.json"


def build_stages(
    *,
    skill_dir: Path,
    py: Path,
    target_skill_dir: Path,
    skill: str,
    model: str,
    run_parity: bool,
) -> list[tuple[str, list[str], dict[str, str]]]:
    """Return ordered (stage_name, argv, extra_env) tuples.

    ``skill`` is the converted skill's name (frontmatter ``name`` or dir name);
    it drives the spec/eval/dist paths the later stages read.
    """
    spec = str(_spec_path(skill_dir, skill))
    test_file = f"evals/test_{skill.replace('-', '_')}.py"
    report = f"training/reports/{skill}.json"
    parity_report = f"training/reports/{skill}.parity.json"
    py_s = str(py)

    stages: list[tuple[str, list[str], dict[str, str]]] = [
        ("extract", [
            py_s, "scripts/extract_graphspec.py", str(target_skill_dir),
            "--skills-root", str(target_skill_dir.parent),
            "--model", model, "--out", spec, "--force",
        ], {}),
        ("validate", [py_s, "scripts/validate_graph.py", spec, "--report", report], {}),
        ("gen_evals", [py_s, "scripts/gen_evals.py", spec], {}),
        ("pytest", [py_s, "-m", "pytest", test_file, "-q"], {}),
        ("package", [py_s, "scripts/package_standalone.py", spec], {}),
    ]
    if run_parity:
        stages.append(
            ("parity", [py_s, "scripts/parity_run.py", spec, "--report", parity_report],
             {"RUN_LIVE_EVALS": "1"})
        )
    stages.append(("improve", [py_s, "scripts/self_improve.py"], {}))
    return stages


# ── streaming runner ─────────────────────────────────────────────────────────
def _run_stage(
    *,
    name: str,
    index: int,
    total: int,
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    on_event: EventCallback,
    handle: ConversionHandle,
) -> StageResult:
    """Run one stage, stream its stdout as LogEvents, return its result."""
    on_event(StageEvent(stage=name, index=index, total=total))
    result = StageResult(name=name)
    tail: list[str] = []

    proc = subprocess.Popen(  # noqa: S603 - argv is a list, shell=False
        argv,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    handle._set_proc(proc)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            on_event(LogEvent(stage=name, line=line))
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)
    finally:
        proc.wait()
        handle._set_proc(None)

    result.exit_code = proc.returncode
    result.ok = proc.returncode == 0
    result.tail = tail
    return result


def run_conversion(
    *,
    target_skill_dir: Path,
    skill_hint: str,
    model: str = "sonnet",
    run_parity: bool = False,
    llm_backend: str = "claude_cli",
    on_event: EventCallback,
    on_handle: Optional[Callable[[ConversionHandle], None]] = None,
) -> dict[str, Any]:
    """Run the full staged conversion. Blocks; call in a worker thread.

    Returns a summary dict ``{skill, status, stages:[...], spec, dist_dir}``.
    Emits a terminal :class:`DoneEvent`; per-stage progress via StageEvent and
    per-line output via LogEvent; failures via ErrorEvent.
    """
    handle = ConversionHandle()
    if on_handle is not None:
        on_handle(handle)

    try:
        skill_dir, py = ensure_available()
    except LangGraphUnavailable as exc:
        on_event(ErrorEvent(message=str(exc), recoverable=False))
        on_event(DoneEvent(status=TrainRunStatus.failed))
        return {"skill": skill_hint, "status": "failed", "error": str(exc), "stages": []}

    env = build_env(llm_backend)

    # Stage 1 runs first to PRODUCE the spec; the converted skill name comes from
    # the spec (frontmatter `name`), which then drives every later stage's paths.
    # We pre-name with the hint and re-resolve from the written spec.
    skill = skill_hint
    stages_meta = build_stages(
        skill_dir=skill_dir, py=py, target_skill_dir=target_skill_dir,
        skill=skill, model=model, run_parity=run_parity,
    )
    total = len(stages_meta)
    results: list[StageResult] = []
    status = TrainRunStatus.completed
    aborted = False  # sticky: once a stage fails (or we cancel), skip all the rest

    for i, (name, argv, extra_env) in enumerate(stages_meta, start=1):
        if aborted or handle.cancelled:
            results.append(StageResult(name=name, skipped=True))
            continue

        stage_env = {**env, **extra_env}
        res = _run_stage(
            name=name, index=i, total=total, argv=argv,
            cwd=skill_dir, env=stage_env, on_event=on_event, handle=handle,
        )
        results.append(res)

        # After extract, re-resolve the real skill name from the written spec so
        # downstream paths are correct even if the hint differed.
        if name == "extract" and res.ok:
            resolved = _skill_name_from_spec(_spec_path(skill_dir, skill))
            if resolved and resolved != skill:
                skill = resolved
                # rebuild the remaining stages' argv with the corrected name
                rebuilt = build_stages(
                    skill_dir=skill_dir, py=py, target_skill_dir=target_skill_dir,
                    skill=skill, model=model, run_parity=run_parity,
                )
                stages_meta = stages_meta[:i] + rebuilt[i:]

        if not res.ok:
            aborted = True
            on_event(ErrorEvent(
                message=f"stage '{name}' failed (exit {res.exit_code}): "
                        + " | ".join(res.tail[-3:]),
                recoverable=False,
            ))

    if handle.cancelled:
        status = TrainRunStatus.cancelled
    elif any((not r.ok and not r.skipped) for r in results):
        status = TrainRunStatus.failed

    dist_dir = skill_dir / "dist" / skill
    on_event(DoneEvent(
        status=status,
        best_skill_path=str(dist_dir) if dist_dir.is_dir() else None,
    ))
    return {
        "skill": skill,
        "status": status.value,
        "stages": [r.to_dict() for r in results],
        "spec": str(_spec_path(skill_dir, skill)),
        "dist_dir": str(dist_dir),
    }


def _skill_name_from_spec(spec_path: Path) -> Optional[str]:
    try:
        data = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = data.get("skill")
    return str(name) if name else None


__all__ = [
    "run_conversion",
    "ConversionHandle",
    "StageResult",
    "LangGraphUnavailable",
    "ensure_available",
    "build_env",
    "build_stages",
]
