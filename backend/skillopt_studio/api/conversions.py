"""Convert-to-LangGraph REST + SSE API.

Endpoints:
- ``POST /api/conversions``             — launch a conversion for a scanned skill.
- ``GET  /api/conversions``             — list conversions.
- ``GET  /api/conversions/{id}``        — status + parsed artifacts.
- ``POST /api/conversions/{id}/cancel`` — SIGTERM the in-flight stage group.
- ``GET  /api/conversions/{id}/events`` — SSE stream (stage/log/error/done).

Wraps the companion ``skill-to-langgraph`` skill via ``langgraph.pipeline`` (a
staged subprocess driver) and reuses the shared ``events.bus`` for SSE — the same
machinery the training runs use. Skill resolution goes through the scanner
registry (imported defensively); the resolved skill dir is confined to the
scanner's source roots before launch.
"""
from __future__ import annotations

import asyncio
import importlib
import threading
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import config
from ..domain import DoneEvent, ErrorEvent, TrainRunStatus
from ..events import bus
from ..langgraph import outputs, pipeline

router = APIRouter(prefix="/api/conversions", tags=["conversions"])

_HEARTBEAT_SECONDS = 15


# ── in-memory registry ───────────────────────────────────────────────────────
class _ConvState:
    def __init__(self, conv_id: str, skill_id: str, skill: str) -> None:
        self.id = conv_id
        self.skill_id = skill_id
        self.skill = skill
        self.status: str = TrainRunStatus.pending.value
        self.handle: Optional[pipeline.ConversionHandle] = None
        self.thread: Optional[threading.Thread] = None
        self.summary: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None


_CONVS: dict[str, _ConvState] = {}
_CONVS_LOCK = threading.Lock()


class ConvertRequest(BaseModel):
    skill_id: str = Field(description="id of a scanned skill (scanner registry)")
    model: str = Field(default="sonnet", description="claude model tier for extraction")
    run_parity: bool = Field(default=False, description="run live GEval parity (costs LLM calls)")
    llm_backend: str = Field(
        default="claude_cli",
        description="'claude_cli' (subscription, scrubs API keys) or 'api' (bills per token)",
    )


# ── skill resolution (defensive scanner import + path confinement) ───────────
def _scan() -> list[Any]:
    try:
        scanner = importlib.import_module("skillopt_studio.scanner")
        return scanner.scan_all(Path.cwd())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"skill scanner unavailable: {exc}") from exc


def _resolve_target_dir(skill_id: str) -> tuple[Path, str]:
    """Return (skill_dir, skill_name) for *skill_id*, or raise 404/400.

    The skill dir is the parent of the skill's SKILL.md ``source_path``. It is
    confined to the discovered scanner source roots to prevent a crafted id from
    pointing the converter at an arbitrary directory.
    """
    skills = _scan()
    match = next((s for s in skills if s.id == skill_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"skill_id not found: {skill_id}")

    src = Path(match.source_path).resolve()
    skill_dir = src.parent
    # Confinement: the skill dir must sit under some scanned skill's root chain.
    roots = {Path(s.source_path).resolve().parent.parent for s in skills}
    if not any(_is_within(skill_dir, r) for r in roots):
        raise HTTPException(status_code=400, detail="resolved skill dir escapes scanned roots")
    return skill_dir, match.name


def _is_within(child: Path, root: Path) -> bool:
    try:
        return child.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


# ── launch ───────────────────────────────────────────────────────────────────
@router.post("")
def create_conversion(req: ConvertRequest) -> dict[str, Any]:
    """Resolve the skill, launch the staged conversion in a worker thread."""
    skill_dir, skill_name = _resolve_target_dir(req.skill_id)

    # Fail fast with a clear 503 if the companion repo/venv is missing.
    try:
        pipeline.ensure_available()
    except pipeline.LangGraphUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    conv_id = uuid.uuid4().hex[:12]
    state = _ConvState(conv_id, req.skill_id, skill_name)
    with _CONVS_LOCK:
        _CONVS[conv_id] = state

    def _on_event(event: Any) -> None:
        bus.publish(conv_id, event)

    def _on_handle(handle: pipeline.ConversionHandle) -> None:
        state.handle = handle
        state.status = TrainRunStatus.running.value

    def _worker() -> None:
        try:
            summary = pipeline.run_conversion(
                target_skill_dir=skill_dir,
                skill_hint=skill_name,
                model=req.model,
                run_parity=req.run_parity,
                llm_backend=req.llm_backend,
                on_event=_on_event,
                on_handle=_on_handle,
            )
            state.summary = summary
            if state.status != TrainRunStatus.cancelled.value:
                state.status = summary.get("status", TrainRunStatus.completed.value)
            state.skill = summary.get("skill", state.skill)
        except Exception as exc:  # noqa: BLE001
            state.error = f"{type(exc).__name__}: {exc}"
            state.status = TrainRunStatus.failed.value
            _on_event(ErrorEvent(message=state.error, recoverable=False))
            _on_event(DoneEvent(status=TrainRunStatus.failed))

    thread = threading.Thread(target=_worker, name=f"convert-{conv_id}", daemon=True)
    state.thread = thread
    state.status = TrainRunStatus.running.value
    thread.start()

    return {"id": conv_id, "skill_id": req.skill_id, "skill": skill_name, "status": state.status}


@router.post("/{conv_id}/cancel")
def cancel_conversion(conv_id: str) -> dict[str, Any]:
    state = _get(conv_id)
    if state.handle is None:
        raise HTTPException(status_code=409, detail="conversion has no live process")
    ok = state.handle.cancel()
    if ok:
        state.status = TrainRunStatus.cancelled.value
    return {"id": conv_id, "cancelled": ok, "status": state.status}


@router.get("")
def list_conversions() -> dict[str, Any]:
    with _CONVS_LOCK:
        states = list(_CONVS.values())
    return {
        "conversions": [
            {"id": s.id, "skill_id": s.skill_id, "skill": s.skill,
             "status": s.status, "error": s.error}
            for s in states
        ]
    }


@router.get("/{conv_id}")
def get_conversion(conv_id: str) -> dict[str, Any]:
    """Status + parsed artifacts (spec shape, 6 checks, dist folder, parity)."""
    state = _get(conv_id)
    payload: dict[str, Any] = {
        "id": state.id,
        "skill_id": state.skill_id,
        "skill": state.skill,
        "status": state.status,
        "error": state.error,
        "stages": (state.summary or {}).get("stages"),
    }
    # Artifacts are read from disk so a still-running conversion shows partials.
    try:
        payload["artifacts"] = outputs.parse_conversion(state.skill)
    except Exception as exc:  # noqa: BLE001
        payload["artifacts"] = None
        payload["artifacts_error"] = str(exc)
    return payload


@router.get("/{conv_id}/events")
async def stream_conversion_events(conv_id: str, request: Request) -> EventSourceResponse:
    """SSE: stream stage/log/error/done events for a conversion."""
    bus.bind_loop(asyncio.get_running_loop())
    channel = bus.channel(conv_id)

    async def _gen() -> AsyncIterator[dict]:
        try:
            async for event in channel.subscribe(replay_backlog=True):
                if await request.is_disconnected():
                    break
                yield {"event": getattr(event, "type", "message"), "data": event.model_dump_json()}
                if isinstance(event, DoneEvent):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            err = ErrorEvent(message=f"stream error: {exc}", recoverable=False)
            yield {"event": "error", "data": err.model_dump_json()}

    return EventSourceResponse(_gen(), ping=_HEARTBEAT_SECONDS, media_type="text/event-stream")


def _get(conv_id: str) -> _ConvState:
    with _CONVS_LOCK:
        state = _CONVS.get(conv_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"conversion not found: {conv_id}")
    return state


__all__ = ["router"]
