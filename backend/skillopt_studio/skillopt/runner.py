"""Subprocess driver for SkillOpt ``train.py`` / ``eval_only.py``.

Launches the SkillOpt CLI with a pre-built argv list (NEVER ``shell=True``) and a
pre-built env (secrets via env only), reads stdout line-by-line (the process is
started with ``PYTHONUNBUFFERED=1``), parses the verified stdout markers into
``domain.SSEEvent`` objects, and pushes them onto a per-run event bus for SSE.

Process group handling (verified pattern): the child is started with
``start_new_session=True`` so cancellation can ``os.killpg(os.getpgid(pid),
SIGTERM)`` to terminate the whole tree (target-model workers included).

STDOUT contract parsed here (see STDOUT_CONTRACT.md):
- ``[EPOCH x/y]``                          → EpochEvent
- ``[STEP x/y]``                           → StepEvent (boundary; resets the
                                             per-step rollout-soft accumulator)
- ``1/6 rollout`` … ``6/6 ...`` (bare OR bracketed) → StageEvent (index/total/stage)
- ``[6/6 EVALUATE] ACCEPT|REJECT … hard=/soft=/mixed=`` → StepEvent w/ sel_score +
                                             accepted; train_score is the MEAN of
                                             this step's per-item rollout soft.
- ``[rollout] id=… hard=0|1 soft=…``        → per-item progress; the soft value is
                                             accumulated into the step train_score
                                             (generic_qa emits no aggregate line).
- ``[baseline result] … hard=… soft=…``     → optional StageEvent (legacy path).
- ``slow update`` / ``meta skill``          → StageEvent (epoch boundary).
- ``error``/``fail``/``Traceback``          → ErrorEvent (recoverable heuristic).

The runner is transport-agnostic: it accepts a callback (``on_event``) so it can
feed an asyncio bus, a queue, or a test list. ``run_train`` blocks until the
process exits; callers run it in a thread/executor.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
from typing import Any, Callable, Mapping, Optional, Sequence

from ..domain import (
    DoneEvent,
    EpochEvent,
    ErrorEvent,
    SSEEvent,
    StageEvent,
    StepEvent,
    TrainRunStatus,
)

EventCallback = Callable[[SSEEvent], None]

# ── Regexes for the verified stdout markers ───────────────────────────────────
_RE_EPOCH = re.compile(r"\[EPOCH\s+(\d+)\s*/\s*(\d+)\]", re.IGNORECASE)
_RE_STEP = re.compile(r"\[STEP\s+(\d+)\s*/\s*(\d+)\]", re.IGNORECASE)
# Stage markers appear bracketed ("[1/6 ROLLOUT]") OR bare ("1/6 rollout"), as
# emitted by the webui/_parse_stage contract. Match both.
_RE_STAGE = re.compile(r"\[?(\d+)\s*/\s*6\s+([A-Za-z][A-Za-z ]*?)\]?(?:\s|$)")
_RE_GATE = re.compile(
    r"\[6/6\s+EVALUATE\]\s+(ACCEPT(?:\s*\(new best\))?|REJECT)",
    re.IGNORECASE,
)
_RE_HARD = re.compile(r"hard\s*=\s*([0-9]*\.?[0-9]+)", re.IGNORECASE)
_RE_SOFT = re.compile(r"soft\s*=\s*([0-9]*\.?[0-9]+)", re.IGNORECASE)
_RE_MIXED = re.compile(r"mixed\[[^\]]*\]\s*=\s*([0-9]*\.?[0-9]+)", re.IGNORECASE)
# generic_qa prints per-item rollout lines as:
#   "    [rollout] id=<id> hard=<0|1> soft=<float>"
_RE_ITEM_ROLLOUT = re.compile(
    r"\[rollout\]\s*id=(\S+)\s+hard=(\d+)\s+soft=([0-9]*\.?[0-9]+)", re.IGNORECASE
)
_RE_BASELINE = re.compile(r"\[baseline result\].*?hard=([0-9.]+).*?soft=([0-9.]+)", re.IGNORECASE)


def _to_float(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_line(line: str, state: dict[str, Any]) -> list[SSEEvent]:
    """Parse one stdout *line* into zero or more SSE events.

    *state* is a mutable dict carried across lines (current step/epoch/totals) so
    score events emitted at the gate can be attributed to the active step.
    """
    events: list[SSEEvent] = []
    low = line.lower()

    m = _RE_EPOCH.search(line)
    if m:
        epoch = int(m.group(1))
        total = int(m.group(2))
        state["epoch"] = epoch
        state["total_epochs"] = total
        events.append(EpochEvent(epoch=epoch, total_epochs=total))

    m = _RE_STEP.search(line)
    if m:
        step = int(m.group(1))
        total = int(m.group(2))
        state["step"] = step
        state["total_steps"] = total
        # New step boundary: reset the per-step rollout-soft accumulator so the
        # train_score is aggregated fresh from this step's [rollout] lines.
        state["rollout_softs"] = []
        state["last_train_score"] = None
        events.append(StepEvent(step=step, total_steps=total))

    m = _RE_STAGE.search(line)
    if m:
        idx = int(m.group(1))
        stage_name = m.group(2).strip().lower()
        events.append(
            StageEvent(step=state.get("step"), stage=stage_name, index=idx, total=6)
        )

    # Gate decision carries the step's scores + accept/reject.
    g = _RE_GATE.search(line)
    if g:
        decision = g.group(1).lower()
        accepted = decision.startswith("accept")
        hard = _to_float(_RE_HARD.search(line).group(1)) if _RE_HARD.search(line) else None
        soft = _to_float(_RE_SOFT.search(line).group(1)) if _RE_SOFT.search(line) else None
        mixed = _to_float(_RE_MIXED.search(line).group(1)) if _RE_MIXED.search(line) else None
        sel = mixed if mixed is not None else (hard if hard is not None else soft)
        # Train score for the step: prefer an explicit baseline line, else the
        # mean of this step's per-item rollout soft scores (generic_qa emits
        # per-item [rollout] lines but no aggregate train line).
        train_score = state.get("last_train_score")
        if train_score is None:
            softs = state.get("rollout_softs") or []
            if softs:
                train_score = sum(softs) / len(softs)
        events.append(
            StepEvent(
                step=state.get("step"),
                total_steps=state.get("total_steps"),
                train_score=train_score,
                sel_score=sel,
                accepted=accepted,
            )
        )

    # "[1/6 done] hard=.. soft=.." — capture the rollout/train score for the step.
    if "1/6 done" in low or "[baseline result]" in low:
        b = _RE_BASELINE.search(line)
        if b:
            state["last_train_score"] = _to_float(b.group(1))
            events.append(
                StageEvent(
                    step=state.get("step"),
                    stage="baseline",
                    index=0,
                    total=6,
                )
            )
        else:
            h = _RE_HARD.search(line)
            if h:
                state["last_train_score"] = _to_float(h.group(1))

    # Per-item rollout progress (generic_qa: "[rollout] id=.. hard=.. soft=..").
    im = _RE_ITEM_ROLLOUT.search(line)
    if im:
        soft = _to_float(im.group(3))
        if soft is not None:
            state.setdefault("rollout_softs", []).append(soft)
        events.append(
            StageEvent(
                step=state.get("step"),
                stage=f"rollout_item:{im.group(1)}:hard={im.group(2)}:soft={im.group(3)}",
                index=1,
                total=6,
            )
        )

    if "slow update" in low:
        events.append(StageEvent(step=state.get("step"), stage="slow update"))
    if "meta skill" in low:
        events.append(StageEvent(step=state.get("step"), stage="meta skill"))

    # Errors / failures. "Traceback" or a leading error keyword → error event.
    if "traceback (most recent call last)" in low:
        events.append(
            ErrorEvent(step=state.get("step"), message=line.strip(), recoverable=False)
        )
    elif re.search(r"\b(error|fail(?:ed|ure)?)\b", low) and "[rollout]" not in low and "fail_reason" not in low:
        # Per-rollout failures (hard=0) are normal; only surface non-rollout errors.
        recoverable = "warning" in low or "retry" in low
        events.append(
            ErrorEvent(step=state.get("step"), message=line.strip(), recoverable=recoverable)
        )

    return events


class RunHandle:
    """Live handle to a running SkillOpt subprocess; supports cancellation."""

    def __init__(self, process: subprocess.Popen, run_id: str) -> None:
        self.process = process
        self.run_id = run_id
        self.status = TrainRunStatus.running
        self._lock = threading.Lock()

    @property
    def pid(self) -> int:
        return self.process.pid

    def cancel(self) -> bool:
        """SIGTERM the whole process group. Returns True if a signal was sent."""
        with self._lock:
            if self.process.poll() is not None:
                return False
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                try:
                    self.process.terminate()
                except OSError:
                    return False
            self.status = TrainRunStatus.cancelled
            return True


def run_train(
    argv: Sequence[str],
    env: Mapping[str, str],
    on_event: EventCallback,
    cwd: Optional[str] = None,
    on_handle: Optional[Callable[[RunHandle], None]] = None,
    run_id: str = "",
) -> TrainRunStatus:
    """Launch *argv*, stream stdout → events via *on_event*, return final status.

    Blocks until the process exits. Emits a terminal :class:`DoneEvent`. Secrets
    must already be in *env*; argv must be a list (no shell). The child runs in a
    new session so the whole tree can be killed on cancel.
    """
    full_env = dict(os.environ)
    full_env.update(env)
    full_env.setdefault("PYTHONUNBUFFERED", "1")

    proc = subprocess.Popen(  # noqa: S603 - argv is a list, shell=False by default
        list(argv),
        cwd=cwd,
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    handle = RunHandle(proc, run_id)
    if on_handle is not None:
        on_handle(handle)

    state: dict[str, Any] = {}
    best_skill_path: Optional[str] = None
    final_test_score: Optional[float] = None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            for event in parse_line(line, state):
                on_event(event)
            # Opportunistically capture final-summary signals.
            m = re.search(r"Output saved to:\s*(\S+)", line)
            if m:
                state["out_root"] = m.group(1)
            mt = re.search(r"Final test:\s*([0-9.]+)", line)
            if mt:
                final_test_score = _to_float(mt.group(1))
    finally:
        proc.wait()

    if handle.status == TrainRunStatus.cancelled:
        status = TrainRunStatus.cancelled
    elif proc.returncode == 0:
        status = TrainRunStatus.completed
        out_root = state.get("out_root")
        if out_root:
            for cand in (os.path.join(out_root, "best_skill.md"),
                         os.path.join(out_root, "skills", "best_skill.md")):
                if os.path.isfile(cand):
                    best_skill_path = cand
                    break
    else:
        status = TrainRunStatus.failed
        on_event(
            ErrorEvent(
                step=state.get("step"),
                message=f"process exited with code {proc.returncode}",
                recoverable=False,
            )
        )

    on_event(
        DoneEvent(
            status=status,
            best_skill_path=best_skill_path,
            final_test_score=final_test_score,
        )
    )
    handle.status = status
    return status


__all__ = ["run_train", "parse_line", "RunHandle", "EventCallback"]
