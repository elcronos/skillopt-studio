"""Server-Sent Events stream for a training run.

``GET /api/runs/{id}/events`` streams ``domain.SSEEvent`` JSON payloads as they
are produced by the runner (via ``events.bus``). Uses ``sse-starlette``'s
``EventSourceResponse`` with a ~15s heartbeat (ping) so proxies/clients keep the
connection alive between sparse events. The stream includes an explicit error
event ``{step, message, recoverable}`` (the runner emits ``ErrorEvent``) and ends
after the terminal ``DoneEvent``.

The event ``event:`` field is the event ``type`` (``epoch``/``step``/``stage``/
``error``/``done``) and ``data:`` is the model's JSON. Frontends switch on the
SSE event name.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..domain import DoneEvent, ErrorEvent
from ..events import bus

router = APIRouter(prefix="/api/runs", tags=["stream"])

_HEARTBEAT_SECONDS = 15


@router.get("/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> EventSourceResponse:
    """Stream SSE events for *run_id* until the run completes or the client leaves."""
    # Bind the bus to this request's running loop (idempotent) so thread-safe
    # publishes from the runner are scheduled correctly.
    bus.bind_loop(asyncio.get_running_loop())
    channel = bus.channel(run_id)

    async def _event_generator() -> AsyncIterator[dict]:
        try:
            async for event in channel.subscribe(replay_backlog=True):
                if await request.is_disconnected():
                    break
                yield {
                    "event": getattr(event, "type", "message"),
                    "data": event.model_dump_json(),
                }
                if isinstance(event, DoneEvent):
                    break
        except asyncio.CancelledError:  # client disconnected
            raise
        except Exception as exc:  # noqa: BLE001 - surface as an explicit error event
            err = ErrorEvent(message=f"stream error: {exc}", recoverable=False)
            yield {"event": "error", "data": err.model_dump_json()}

    return EventSourceResponse(
        _event_generator(),
        ping=_HEARTBEAT_SECONDS,
        media_type="text/event-stream",
    )


__all__ = ["router"]
