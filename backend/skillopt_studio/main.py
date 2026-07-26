"""FastAPI application entrypoint for SkillOpt Studio.

Routers from ``api/`` are mounted defensively: each import is wrapped so that a
not-yet-built router (built in parallel by other feature packages) logs a warning
and is skipped instead of crashing startup. On startup the fixture-replay schema
probe runs against the golden run, surfacing schema divergence early.

Run with::

    uvicorn skillopt_studio.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, config
from .events import bus as _event_bus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("skillopt_studio.main")

# Routers to mount, in order. ``health`` exists at the foundation stage; the rest
# are built by other agents and imported defensively.
_ROUTER_MODULES: tuple[str, ...] = (
    "health",
    "skills",
    "graph",
    "datasets",
    "graders",
    "models",
    "runs",
    "stream",
    "ai",
    "conversions",
)


def _mount_routers(app: FastAPI) -> list[str]:
    """Import and include each available router; skip missing ones. Returns the
    list of successfully mounted module names."""
    mounted: list[str] = []
    for name in _ROUTER_MODULES:
        try:
            module = importlib.import_module(f".api.{name}", package=__package__)
        except Exception as exc:  # noqa: BLE001 - router not built yet is expected
            logger.warning("router '%s' not mounted (not available): %s", name, exc)
            continue
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            logger.warning("router '%s' has no APIRouter named 'router'; skipped", name)
            continue
        app.include_router(router)
        mounted.append(name)
        logger.info("mounted router: %s", name)
    return mounted


def _run_schema_probe() -> None:
    """Run the fixture-replay schema probe on startup via skillopt/probe.py if present."""
    try:
        probe = importlib.import_module("skillopt_studio.skillopt.probe")
    except Exception:  # noqa: BLE001
        logger.warning(
            "startup schema probe skipped: skillopt.probe not available yet "
            "(golden_run dir present: %s)",
            config.GOLDEN_RUN_DIR.exists(),
        )
        return
    runner = getattr(probe, "run_probe", None) or getattr(probe, "main", None)
    if runner is None:
        logger.warning("startup schema probe skipped: no run_probe() in skillopt.probe")
        return
    try:
        result = runner()
        logger.info("startup schema probe: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("startup schema probe raised; continuing (server not hard-failed)")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    # ``mounted`` is populated by _mount_routers below (after app construction) and
    # closed over by both the lifespan handler and root(); a shared list keeps that
    # single source of truth without a forward reference.
    mounted: list[str] = []

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:  # pragma: no cover - runtime
        config.ensure_dirs()
        # Bind the event-bus loop at startup (BEFORE any worker-thread /train
        # publish) so SSE publishes from the runner thread are always valid, even
        # if no SSE client has connected yet (loop-race fix).
        _event_bus.bind_loop(asyncio.get_running_loop())
        logger.info(
            "SkillOpt Studio v%s starting (python %s); mounted routers: %s",
            __version__,
            config.python_version_string(),
            ", ".join(mounted) or "(none)",
        )
        _run_schema_probe()
        yield

    app = FastAPI(
        title="SkillOpt Studio",
        version=__version__,
        description="Local studio for optimizing any skill with Microsoft SkillOpt (MIT).",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.CORS_ORIGINS),
        # No cookies / auth are used, so credentials are disabled and methods are
        # enumerated explicitly (security hardening #13).
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    mounted.extend(_mount_routers(app))

    @app.get("/")
    def root() -> dict[str, object]:
        """Return app info."""
        return {
            "app": "SkillOpt Studio",
            "version": __version__,
            "python_version": config.python_version_string(),
            "skillopt_sha": config.SKILLOPT_PINNED_SHA,
            "mounted_routers": mounted,
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
