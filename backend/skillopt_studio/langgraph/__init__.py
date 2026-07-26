"""LangGraph-conversion feature package.

Wraps the companion ``skill-to-langgraph`` skill (a separate repo, located via
``config.LANGGRAPH_SKILL_DIR``) as a staged subprocess pipeline that turns a
scanned skill's ``SKILL.md`` into a runnable ``dist/<skill>/`` LangGraph project.

Mirrors the existing ``skillopt/`` driver: argv lists (never ``shell=True``),
secrets/env controlled explicitly, stdout streamed line-by-line onto the shared
``events.bus`` for SSE, and a process-group handle for cancellation.

Public surface:
- ``pipeline.run_conversion(...)``  — blocking staged runner (call in a thread).
- ``pipeline.ConversionHandle``     — cancel the in-flight stage's process group.
- ``outputs.parse_conversion(...)`` — defensive parse of the produced artifacts.
"""

from . import outputs, pipeline  # noqa: F401

__all__ = ["pipeline", "outputs"]
