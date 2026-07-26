"""Model-configuration API.

CRUD over named ``ModelConfig`` entries (backend + model selection). Secrets are
NEVER stored in the config and NEVER returned: API keys go to the OS keyring via
``keys.store`` keyed by ``(backend, role)``, and only key PRESENCE is reported.

Configs are persisted as a single JSON map under ``configs/model_configs.json``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config
from ..domain import ModelConfig
from ..keys import store as key_store

logger = logging.getLogger("skillopt_studio.api.models")

router = APIRouter(prefix="/api/models", tags=["models"])

_CONFIGS_PATH: Path = config.CONFIGS_DIR / "model_configs.json"


def _read_all() -> dict[str, dict[str, Any]]:
    if not _CONFIGS_PATH.exists():
        return {}
    try:
        data = json.loads(_CONFIGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        logger.warning("model_configs.json unreadable; treating as empty")
        return {}


def _write_all(data: dict[str, dict[str, Any]]) -> None:
    config.CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class ModelConfigCreate(BaseModel):
    """Create/replace a named model config, optionally setting role API keys.

    ``optimizer_api_key`` / ``target_api_key`` are write-only: they are stored in
    the keyring keyed by ``(backend, role)`` and never echoed back.
    """

    name: str
    model: ModelConfig
    optimizer_api_key: Optional[str] = None
    target_api_key: Optional[str] = None


class ModelConfigInfo(BaseModel):
    """Model config with key PRESENCE flags (never the key values)."""

    name: str
    model: ModelConfig
    has_optimizer_key: bool = False
    has_target_key: bool = False


def _info(name: str, model: ModelConfig) -> ModelConfigInfo:
    opt_backend = model.optimizer_backend or model.backend
    tgt_backend = model.target_backend or model.backend
    return ModelConfigInfo(
        name=name,
        model=model,
        has_optimizer_key=key_store.has_key(opt_backend, "optimizer"),
        has_target_key=key_store.has_key(tgt_backend, "target"),
    )


@router.get("")
def list_models() -> list[ModelConfigInfo]:
    """List named model configs with key-presence flags (no key values)."""
    return [_info(name, ModelConfig(**raw)) for name, raw in sorted(_read_all().items())]


@router.get("/{name}")
def get_model(name: str) -> ModelConfigInfo:
    """Return a named model config (no key values)."""
    raw = _read_all().get(name)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"model config '{name}' not found")
    return _info(name, ModelConfig(**raw))


@router.post("", status_code=201)
def create_model(payload: ModelConfigCreate) -> ModelConfigInfo:
    """Create/replace a model config and optionally store role API keys."""
    data = _read_all()
    data[payload.name] = payload.model.model_dump()
    _write_all(data)

    if payload.optimizer_api_key:
        backend = payload.model.optimizer_backend or payload.model.backend
        key_store.set_key(backend, "optimizer", payload.optimizer_api_key)
    if payload.target_api_key:
        backend = payload.model.target_backend or payload.model.backend
        key_store.set_key(backend, "target", payload.target_api_key)

    return _info(payload.name, payload.model)


@router.delete("/{name}")
def delete_model(name: str) -> dict[str, bool]:
    """Delete a model config. Keyring secrets are left intact (shared per backend)."""
    data = _read_all()
    if name not in data:
        raise HTTPException(status_code=404, detail=f"model config '{name}' not found")
    del data[name]
    _write_all(data)
    return {"deleted": True}
