"""Per-run async event bus feeding the SSE stream.

Each training run gets a dedicated :class:`RunChannel` backed by an
``asyncio.Queue``. The runner (running in a worker thread) publishes
``domain.SSEEvent`` objects via :meth:`EventBus.publish`, which are forwarded to
the channel's queue thread-safely (``call_soon_threadsafe``). The SSE endpoint
consumes the queue with :meth:`RunChannel.subscribe`.

A bounded ring buffer of recent events is retained per channel so a client that
connects slightly late (or reconnects) can be replayed the backlog before live
streaming. The terminal ``DoneEvent`` closes the channel.
"""
from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import AsyncIterator, Optional

from ..domain import DoneEvent, SSEEvent

_BACKLOG_MAX = 1000


class RunChannel:
    """A single run's event stream: a queue + bounded replay backlog."""

    def __init__(self, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.run_id = run_id
        self._loop = loop
        self._queue: asyncio.Queue[Optional[SSEEvent]] = asyncio.Queue()
        self._backlog: deque[SSEEvent] = deque(maxlen=_BACKLOG_MAX)
        self._closed = False

    # ── Producer side (called from the runner thread) ──────────────────────
    def publish_threadsafe(self, event: SSEEvent) -> None:
        """Publish from any thread. Schedules the put on the bus's event loop."""
        self._loop.call_soon_threadsafe(self._publish, event)

    def _publish(self, event: SSEEvent) -> None:
        if self._closed:
            return
        self._backlog.append(event)
        self._queue.put_nowait(event)
        if isinstance(event, DoneEvent):
            self._closed = True
            self._queue.put_nowait(None)  # sentinel: end of stream

    # ── Consumer side (called from the SSE handler) ────────────────────────
    async def subscribe(self, replay_backlog: bool = True) -> AsyncIterator[SSEEvent]:
        """Yield events: optional backlog replay, then live until DoneEvent."""
        if replay_backlog:
            for event in list(self._backlog):
                yield event
                if isinstance(event, DoneEvent):
                    return
        if self._closed and not self._queue.qsize():
            return
        while True:
            event = await self._queue.get()
            if event is None:  # sentinel
                return
            yield event
            if isinstance(event, DoneEvent):
                return

    @property
    def closed(self) -> bool:
        return self._closed


class EventBus:
    """Registry of per-run channels. One instance per app."""

    def __init__(self) -> None:
        self._channels: dict[str, RunChannel] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the asyncio loop the SSE endpoints run on. Call once at startup."""
        self._loop = loop

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        # Best-effort: the running loop (when called from async context).
        return asyncio.get_event_loop()

    def channel(self, run_id: str) -> RunChannel:
        """Get or create the channel for *run_id*."""
        with self._lock:
            ch = self._channels.get(run_id)
            if ch is None:
                ch = RunChannel(run_id, self._get_loop())
                self._channels[run_id] = ch
            return ch

    def publish(self, run_id: str, event: SSEEvent) -> None:
        """Publish an event to a run's channel (thread-safe)."""
        self.channel(run_id).publish_threadsafe(event)

    def has_channel(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._channels

    def drop(self, run_id: str) -> None:
        """Remove a finished channel to free memory."""
        with self._lock:
            self._channels.pop(run_id, None)


# Module-level singleton shared by the runner driver and the SSE endpoint.
bus = EventBus()

__all__ = ["EventBus", "RunChannel", "bus"]
