"""Generate a per-run SkillOpt config for the generic_qa env.

Writes ``configs/generic_qa/<slug>.yaml`` that inherits the SkillOpt base via
``_base_`` and sets ``env.name: generic_qa`` + the user's skill/dataset/scoring
and model/train/optimizer params. SkillOpt's ``load_config`` resolves ``_base_``
relative to the config file, then flattens; the flattened keys are what the
adapter constructor receives (see ``get_adapter`` in train.py).

The generated config carries a ``scoring`` block under ``env`` so the
``GenericQAEnv`` constructor receives it as the ``scoring`` kwarg after flatten.
Secrets are NEVER written here — model creds come from the subprocess env.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Path the cloned SkillOpt checkout's base config lives at, relative to the
# generated config's location. SkillOpt resolves _base_ relative to the file.
# We point at the studio-local configs/_base_/default.yaml which itself mirrors
# the SkillOpt base (written by ensure_base_config below).
_BASE_REL = "../_base_/default.yaml"

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def slugify(name: str) -> str:
    """Return a filesystem/registry-safe slug for *name*."""
    s = str(name).strip().lower().replace(" ", "-")
    s = _SLUG_RE.sub("-", s).strip("-._")
    return s or "run"


def ensure_base_config(configs_dir: str | Path) -> Path:
    """Ensure ``configs/_base_/default.yaml`` exists, mirroring the SkillOpt base.

    The generated per-run config inherits from this. We keep a studio-local copy
    (sourced from ``reference/skillopt_base_config.yaml``) so config resolution
    does not depend on the cloned checkout's path layout.
    """
    import yaml  # local import; pyyaml is a studio dependency

    base_dir = Path(configs_dir) / "_base_"
    base_dir.mkdir(parents=True, exist_ok=True)
    base_path = base_dir / "default.yaml"
    if base_path.is_file():
        return base_path

    # Source from the reference copy when available; else write a minimal base.
    ref = Path(__file__).resolve().parents[3] / "reference" / "skillopt_base_config.yaml"
    if ref.is_file():
        base_path.write_text(ref.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        base_path.write_text(yaml.safe_dump(_MINIMAL_BASE, sort_keys=False), encoding="utf-8")
    return base_path


_MINIMAL_BASE: dict[str, Any] = {
    "model": {
        "backend": "openai_chat",
        "optimizer": "gpt-5.5",
        "target": "gpt-5.5",
        "optimizer_backend": "openai_chat",
        "target_backend": "openai_chat",
        "reasoning_effort": "medium",
    },
    "train": {"num_epochs": 4, "batch_size": 40, "accumulation": 1, "seed": 42},
    "gradient": {"minibatch_size": 8, "analyst_workers": 16, "failure_only": False},
    "optimizer": {
        "learning_rate": 4,
        "min_learning_rate": 2,
        "lr_scheduler": "cosine",
        "skill_update_mode": "patch",
        "use_slow_update": True,
        "use_meta_skill": True,
    },
    "evaluation": {"use_gate": True, "sel_env_num": 0, "test_env_num": 0, "eval_test": True},
    "env": {"name": "", "split_mode": "ratio", "split_seed": 42, "exec_timeout": 120},
}


def build_config_dict(
    *,
    slug: str,
    skill_init_path: str,
    data_path: str,
    out_root: str,
    scoring: dict[str, Any],
    model: dict[str, Any] | None = None,
    train: dict[str, Any] | None = None,
    optimizer: dict[str, Any] | None = None,
    gradient: dict[str, Any] | None = None,
    evaluation: dict[str, Any] | None = None,
    split_mode: str = "ratio",
    split_ratio: str = "2:1:7",
    split_seed: int = 42,
    split_dir: str = "",
    exec_timeout: int = 120,
    custom_code_path: str = "",
) -> dict[str, Any]:
    """Return the config mapping (pre-YAML) for one generic_qa run.

    ``scoring`` is validated/clamped: ``threshold`` ∈ [0,1]; ``type`` must be a
    known scorer. Model creds are intentionally absent (env-injected).

    Partial section dicts (``model``/``train``/``optimizer``/``gradient``/
    ``evaluation``) are emitted as SUB-MAPS so SkillOpt's real ``load_config``
    deep-merge layers them onto the ``_base_`` defaults WITHOUT wiping base
    sub-keys (e.g. setting only ``optimizer.learning_rate`` keeps base
    ``optimizer.lr_scheduler``/``skill_update_mode``/...). ``evaluation.use_gate``
    is NEVER set false here (flatten raises if false in this branch); we leave it
    inherited as ``true`` and never override it.

    ``custom_code`` is NEVER inlined: the caller writes user scorer code to a
    sidecar file and passes only ``custom_code_path`` (which the env's sandbox
    loads). The scoring block carries the path, not the code.
    """
    stype = str(scoring.get("type", "f1")).strip().lower()
    valid = {"exact", "fuzzy", "f1", "llm_judge", "geval", "custom_python"}
    if stype not in valid:
        raise ValueError(f"scoring.type must be one of {sorted(valid)}, got {stype!r}")
    threshold = scoring.get("threshold", 0.5)
    try:
        threshold = max(0.0, min(1.0, float(threshold)))
    except (TypeError, ValueError):
        threshold = 0.5

    scoring_block: dict[str, Any] = {"type": stype, "threshold": threshold}
    # Persisted scoring keys: never includes raw custom_code (security #11).
    for opt_key in ("answer_parse", "judge_model", "rubric", "criteria"):
        if scoring.get(opt_key):
            scoring_block[opt_key] = scoring[opt_key]
    scoring_block.setdefault("answer_parse", "answer_tag")
    if stype == "custom_python" and custom_code_path:
        scoring_block["custom_code_path"] = str(custom_code_path)

    cfg: dict[str, Any] = {"_base_": _BASE_REL}
    # Only emit sections the caller customized; deep-merge preserves base sub-keys.
    if model:
        cfg["model"] = dict(model)
    if train:
        cfg["train"] = dict(train)
    if optimizer:
        cfg["optimizer"] = dict(optimizer)
    if gradient:
        cfg["gradient"] = dict(gradient)
    if evaluation:
        # Guard: never drop the mandatory validation gate.
        ev = dict(evaluation)
        if ev.get("use_gate") is False:
            ev.pop("use_gate", None)
        cfg["evaluation"] = ev

    env_block: dict[str, Any] = {
        "name": "generic_qa",
        "skill_init": str(skill_init_path),
        "data_path": str(data_path),
        "split_mode": split_mode,
        "split_ratio": split_ratio,
        "split_seed": int(split_seed),
        "exec_timeout": int(exec_timeout),
        "out_root": str(out_root),
        "scoring": scoring_block,
    }
    if split_mode == "split_dir" and split_dir:
        env_block["split_dir"] = str(split_dir)
    cfg["env"] = env_block
    return cfg


def write_config(
    config_dict: dict[str, Any],
    slug: str,
    configs_dir: str | Path,
) -> Path:
    """Write *config_dict* to ``configs/generic_qa/<slug>.yaml`` and return its path."""
    import yaml

    ensure_base_config(configs_dir)
    target_dir = Path(configs_dir) / "generic_qa"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{slugify(slug)}.yaml"
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config_dict, fh, sort_keys=False, allow_unicode=True)
    return path


def write_custom_code_sidecar(custom_code: str, slug: str, configs_dir: str | Path) -> Path:
    """Write user custom-scorer code to a chmod-600 sidecar file; return its path.

    The code is NEVER inlined into the YAML config. The env's sandbox loads it by
    this path (security hardening #11). The file lives under the run's configs dir.
    """
    target_dir = Path(configs_dir) / "generic_qa" / "custom_code"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{slugify(slug)}.py"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(custom_code)
    os.chmod(path, 0o600)
    return path


def generate(
    *,
    slug: str,
    skill_init_path: str,
    data_path: str,
    out_root: str,
    scoring: dict[str, Any],
    configs_dir: str | Path,
    custom_code: str = "",
    **kwargs: Any,
) -> Path:
    """Convenience: build + write the config in one call. Returns the YAML path.

    When ``custom_code`` is supplied (custom_python scorer) it is written to a
    chmod-600 sidecar file and only its path is recorded in the config.
    """
    custom_code_path = ""
    stype = str(scoring.get("type", "")).strip().lower()
    if stype == "custom_python" and custom_code.strip():
        custom_code_path = str(write_custom_code_sidecar(custom_code, slug, configs_dir))

    cfg = build_config_dict(
        slug=slug,
        skill_init_path=skill_init_path,
        data_path=data_path,
        out_root=out_root,
        scoring=scoring,
        custom_code_path=custom_code_path,
        **kwargs,
    )
    return write_config(cfg, slug, configs_dir)


__all__ = [
    "slugify",
    "ensure_base_config",
    "build_config_dict",
    "write_config",
    "write_custom_code_sidecar",
    "generate",
]
