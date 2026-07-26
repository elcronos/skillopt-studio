"""Per-run async event plumbing for the SSE stream.

Exposes the shared :data:`bus` singleton and the :class:`EventBus` /
:class:`RunChannel` types. The runner publishes ``domain.SSEEvent``s to a run's
channel; the ``/api/runs/{id}/events`` endpoint subscribes to it.
"""
from __future__ import annotations

from .bus import EventBus, RunChannel, bus

__all__ = ["EventBus", "RunChannel", "bus"]
