"""Training-run REST API.

Endpoints (mounted under no extra prefix; paths are absolute):
- ``POST /api/runs/train``      — create + launch a run (skill+dataset+model+grader).
- ``POST /api/runs/{id}/eval``  — launch eval_only for a finished run's best skill.
- ``POST /api/runs/{id}/cancel``— SIGTERM the run's process group.
- ``GET  /api/runs``            — list runs (status + slug).
- ``GET  /api/runs/{id}``       — run detail: status + parsed outputs (or partial on fail).

Launching is non-blocking: the subprocess runs in a thread (``runner.run_train``)
and publishes SSE events to ``events.bus``; this module keeps an in-memory run
registry. ``main.py`` mounts this ``router``; we do NOT edit ``main.py``.

NOTE: secret resolution (keyring) and dataset/skill persistence are owned by other
backend packages (``keys/``, ``dataset/``, ``scanner/``). We import them DEFENSIVELY:
if unavailable, the relevant request returns a clear 503/400 rather than crashing
import. Model creds are passed to the runner via env only (never argv/logs).
"""
from __future__ import annotations

import importlib
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config
from ..domain import GraderConfig, ModelConfig, TrainRun, TrainRunStatus
from ..events import bus
from ..skillopt import args as args_mod
from ..skillopt import configgen, outputs, recovery, runner

router = APIRouter(prefix="/api/runs", tags=["runs"])


# ── Path confinement (security hardening) ────────────────────────────────────
def _confined(p: str | Path, root: Path) -> Path:
    """Resolve *p* and assert it stays within *root*; raise 400 on escape.

    Prevents a caller-supplied skill_path/dataset_path from pointing outside the
    studio workspace (path traversal). Both paths are resolved before comparison.
    """
    root_resolved = Path(root).resolve()
    try:
        resolved = Path(p).resolve()
    except (OSError, RuntimeError) as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid path: {p}") from exc
    if not resolved.is_relative_to(root_resolved):
        raise HTTPException(
            status_code=400,
            detail=f"path escapes workspace root: {p}",
        )
    return resolved


# ── In-memory run registry ──────────────────────────────────────────────────
class _RunState:
    def __init__(self, run: TrainRun) -> None:
        self.run = run
        self.handle: Optional[runner.RunHandle] = None
        self.thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None


_RUNS: dict[str, _RunState] = {}
_RUNS_LOCK = threading.Lock()


# ── Request/response models ──────────────────────────────────────────────────
class TrainParams(BaseModel):
    """Frontend-friendly training hyperparameters (nested ``train`` block).

    These are mapped server-side into the generated SkillOpt config:
    - ``num_epochs``/``batch_size``/``seed`` → ``train.*``
    - ``learning_rate`` → ``optimizer.learning_rate`` (edit_budget)
    - ``lr_scheduler`` → ``optimizer.lr_scheduler``
    - ``analyst_workers`` → ``gradient.analyst_workers``
    - ``eval_only`` → ``evaluation.eval_test`` toggle (informational)
    """

    num_epochs: Optional[int] = None
    batch_size: Optional[int] = None
    learning_rate: Optional[int] = None
    lr_scheduler: Optional[str] = None
    analyst_workers: Optional[int] = None
    seed: Optional[int] = None
    eval_only: bool = False


class TrainRequest(BaseModel):
    """Create-and-launch payload.

    Two entry shapes are accepted:
    - FRONTEND shape: ``{skill_id, dataset_name, model_config|model, grader,
      train:{...}}`` — paths resolved server-side (skill_id→scanned skill body
      written to a workspace file; dataset_name→materialized dataset.json).
    - DIRECT shape: ``skill_path``/``dataset_path`` are absolute paths the studio
      already materialized (skill .md + dataset.json). Still supported.
    """

    slug: str = Field(default="run", description="Human-readable run name; slugified for files.")
    skill_id: str = ""
    skill_path: str = ""
    dataset_name: str = "dataset"
    dataset_path: str = ""
    # ``model`` is the canonical field; ``model_config`` is accepted as an alias
    # (frontend-friendly) and merged in the validator below.
    model: ModelConfig = Field(default_factory=ModelConfig)
    grader: GraderConfig = Field(default_factory=GraderConfig)
    train: TrainParams = Field(default_factory=TrainParams)
    split_mode: str = "ratio"
    split_ratio: str = "2:1:7"
    split_dir: str = ""
    # Back-compat flat hyperparameters (override ``train`` when set).
    num_epochs: Optional[int] = None
    batch_size: Optional[int] = None
    seed: Optional[int] = None
    launch: bool = Field(default=True, description="Set false to only generate config (dry).")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    def __init__(self, **data: Any) -> None:
        # Accept the frontend ``model_config`` alias for the model selection.
        if "model_config" in data and "model" not in data:
            data["model"] = data.pop("model_config")
        super().__init__(**data)


def _grader_to_scoring(grader: GraderConfig) -> dict[str, Any]:
    """Map the domain GraderConfig → the env scoring spec block."""
    spec: dict[str, Any] = {
        "type": grader.type.value if hasattr(grader.type, "value") else str(grader.type),
        "threshold": grader.threshold,
        "answer_parse": "answer_tag",
    }
    if grader.rubric:
        spec["rubric"] = grader.rubric
        spec["criteria"] = grader.rubric
    if grader.judge_model:
        spec["judge_model"] = grader.judge_model
    # NOTE: custom_code is intentionally NOT placed here — it must never be
    # persisted into the YAML config. configgen writes it to a chmod-600 sidecar
    # file and the env's sandbox loads it by path (security hardening #11).
    return spec


def _keys_module():
    """Import the keyring package defensively (None if unavailable)."""
    try:
        return importlib.import_module("skillopt_studio.keys")
    except Exception:  # noqa: BLE001
        return None


def _resolve_role_secrets(model: ModelConfig) -> dict[str, Optional[str]]:
    """Resolve per-role API keys via ``keys.get_key(backend, role)``.

    Keys are stored keyed ``"{backend}/{role}"`` (see ``keys/store.py``). We look
    up the optimizer key under ``model.optimizer_backend or model.backend`` and
    the target key under ``model.target_backend or model.backend``. A shared key
    stored under the base ``model.backend`` (role ``"optimizer"`` absent) is used
    as a fallback so single-key setups keep working. Returns a dict with
    ``optimizer``/``target``/``shared`` (any may be None). Values are never logged.
    """
    keys = _keys_module()
    out: dict[str, Optional[str]] = {"optimizer": None, "target": None, "shared": None}
    if keys is None:
        return out
    get_key = getattr(keys, "get_key", None)
    if not callable(get_key):
        return out
    opt_backend = model.optimizer_backend or model.backend
    tgt_backend = model.target_backend or model.backend
    try:
        out["optimizer"] = get_key(opt_backend, "optimizer")
        out["target"] = get_key(tgt_backend, "target")
        # Shared/base key fallback (covers either role if its specific key absent).
        out["shared"] = get_key(model.backend, "optimizer") or get_key(model.backend, "target")
    except Exception:  # noqa: BLE001
        pass
    return out


def _build_role_env(model: ModelConfig) -> dict[str, str]:
    """Build the subprocess env with per-role secrets injected (never argv)."""
    secrets = _resolve_role_secrets(model)
    return args_mod.build_model_env(
        model,
        secret=secrets.get("shared"),
        optimizer_secret=secrets.get("optimizer"),
        target_secret=secrets.get("target"),
    )


def _build_model_section(model: ModelConfig) -> dict[str, Any]:
    section: dict[str, Any] = {
        "backend": model.backend,
        "optimizer": model.optimizer_model,
        "target": model.target_model,
        "optimizer_backend": model.optimizer_backend or model.backend,
        "target_backend": model.target_backend or model.backend,
        "reasoning_effort": model.reasoning_effort,
    }
    return section


# ── Server-side skill/dataset resolution ─────────────────────────────────────
def _workspace_root() -> Path:
    return Path(config.REPO_ROOT).resolve()


def _resolve_skill_path(req: "TrainRequest", slug: str) -> Path:
    """Resolve the seed-skill .md path, confined to the workspace.

    Priority:
    1. ``skill_path`` (DIRECT shape): confined + must exist.
    2. ``skill_id`` (FRONTEND shape): scan providers for the matching skill, write
       its body to ``configs/generic_qa/skills/<slug>.md`` (a workspace file), and
       return that path. SkillOpt optimizes this seed file.
    """
    root = _workspace_root()
    if req.skill_path:
        p = _confined(req.skill_path, root)
        if not p.is_file():
            raise HTTPException(status_code=400, detail=f"skill_path not found: {req.skill_path}")
        return p
    if not req.skill_id:
        raise HTTPException(status_code=400, detail="either skill_path or skill_id is required")

    try:
        scanner = importlib.import_module("skillopt_studio.scanner")
        scan_all = getattr(scanner, "scan_all")
        skills = scan_all(Path.cwd())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"skill scanner unavailable: {exc}") from exc

    match = next((s for s in skills if s.id == req.skill_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"skill_id not found: {req.skill_id}")

    skills_dir = config.CONFIGS_DIR / "generic_qa" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    seed_path = skills_dir / f"{slug}.md"
    body = match.body or ""
    if not body and match.source_path:
        try:
            body = Path(match.source_path).read_text(encoding="utf-8")
        except OSError:
            body = ""
    seed_path.write_text(body, encoding="utf-8")
    return _confined(seed_path, root)


def _resolve_dataset_path(req: "TrainRequest") -> Path:
    """Resolve the dataset.json path, confined to the workspace.

    Priority:
    1. ``dataset_path`` (DIRECT shape): confined + must exist.
    2. ``dataset_name`` (FRONTEND shape): materialize via ``dataset.store`` and
       return the dataset.json path.
    """
    root = _workspace_root()
    if req.dataset_path:
        p = _confined(req.dataset_path, root)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"dataset_path not found: {req.dataset_path}")
        return p

    try:
        store = importlib.import_module("skillopt_studio.dataset.store")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"dataset store unavailable: {exc}") from exc
    dpath = store.data_path(req.dataset_name)
    if dpath is None:
        raise HTTPException(status_code=404, detail=f"dataset not found: {req.dataset_name}")
    return _confined(dpath, root)


def _build_param_sections(req: "TrainRequest") -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Map the frontend ``train`` block (+ back-compat flat fields) into the
    generated config's ``train`` / ``optimizer`` / ``gradient`` sections.

    Returns ``(train_section, optimizer_section, gradient_section)`` — any may be
    empty (the generator omits empty sections, preserving base sub-keys via the
    real load_config deep-merge)."""
    t = req.train
    train_section: dict[str, Any] = {}
    optimizer_section: dict[str, Any] = {}
    gradient_section: dict[str, Any] = {}

    num_epochs = req.num_epochs if req.num_epochs is not None else t.num_epochs
    batch_size = req.batch_size if req.batch_size is not None else t.batch_size
    seed = req.seed if req.seed is not None else t.seed

    if num_epochs is not None:
        train_section["num_epochs"] = int(num_epochs)
    if batch_size is not None:
        train_section["batch_size"] = int(batch_size)
    if seed is not None:
        train_section["seed"] = int(seed)

    if t.learning_rate is not None:
        optimizer_section["learning_rate"] = int(t.learning_rate)
    if t.lr_scheduler:
        optimizer_section["lr_scheduler"] = str(t.lr_scheduler)
    if t.analyst_workers is not None:
        gradient_section["analyst_workers"] = int(t.analyst_workers)

    return train_section, optimizer_section, gradient_section


def _run_payload(run: TrainRun, *, config_path: str = "", launched: bool = False,
                 error: Optional[str] = None) -> dict[str, Any]:
    """A TrainRun-shaped response payload (frontend-aligned)."""
    return {
        "id": run.id,
        "slug": run.slug,
        "skill_id": run.skill_id,
        "dataset_name": run.dataset_name,
        "model_config": run.model_config_.model_dump(),
        "status": run.status.value,
        "run_dir": run.run_dir,
        "created_at": run.created_at.isoformat(),
        "config_path": config_path,
        "launched": launched,
        "error": error,
    }


@router.post("/train")
def create_train_run(req: TrainRequest) -> dict[str, Any]:
    """Generate the config and (optionally) launch the training subprocess.

    Accepts the frontend shape (skill_id/dataset_name/model_config/grader/train)
    or the direct shape (skill_path/dataset_path). Paths are resolved server-side
    and confined to the workspace root; the response is TrainRun-shaped."""
    run_id = uuid.uuid4().hex[:12]
    slug = configgen.slugify(req.slug) + "-" + run_id[:6]
    out_root = str(config.OUTPUTS_DIR / "generic_qa" / slug)

    skill_path = _resolve_skill_path(req, slug)
    dataset_path = _resolve_dataset_path(req)

    train_section, optimizer_section, gradient_section = _build_param_sections(req)
    scoring = _grader_to_scoring(req.grader)
    # Custom scorer code is written to a workspace sidecar file (never inlined in
    # the persisted YAML); the env's sandbox loads it by path. See configgen.
    custom_code = req.grader.custom_code or ""

    try:
        cfg_path = configgen.generate(
            slug=slug,
            skill_init_path=str(skill_path),
            data_path=str(dataset_path),
            out_root=out_root,
            scoring=scoring,
            configs_dir=config.CONFIGS_DIR,
            model=_build_model_section(req.model),
            train=train_section or None,
            optimizer=optimizer_section or None,
            gradient=gradient_section or None,
            split_mode=req.split_mode,
            split_ratio=req.split_ratio,
            split_dir=req.split_dir,
            custom_code=custom_code,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"config generation failed: {exc}") from exc

    run = TrainRun(
        id=run_id,
        slug=slug,
        skill_id=req.skill_id or str(skill_path),
        dataset_name=req.dataset_name,
        model_config=req.model,
        status=TrainRunStatus.pending,
        run_dir=out_root,
    )
    state = _RunState(run)
    with _RUNS_LOCK:
        _RUNS[run_id] = state

    if not req.launch:
        return _run_payload(run, config_path=str(cfg_path), launched=False)

    argv = args_mod.build_train_argv(
        config_path=cfg_path,
        skillopt_clone_dir=config.SKILLOPT_CLONE_DIR,
        python_executable=str(config.VENV_PYTHON) if config.VENV_PYTHON.exists() else None,
    )
    env = _build_role_env(req.model)

    _launch(state, argv, env, run_id)
    return _run_payload(run, config_path=str(cfg_path), launched=True)


def _launch(state: _RunState, argv: list[str], env: dict[str, str], run_id: str) -> None:
    """Spawn the runner in a background thread; wire events to the bus."""

    def _on_event(event: Any) -> None:
        bus.publish(run_id, event)

    def _on_handle(handle: runner.RunHandle) -> None:
        state.handle = handle
        state.run.status = TrainRunStatus.running

    def _worker() -> None:
        try:
            status = runner.run_train(
                argv=argv,
                env=env,
                on_event=_on_event,
                cwd=str(config.SKILLOPT_CLONE_DIR) if Path(config.SKILLOPT_CLONE_DIR).is_dir() else None,
                on_handle=_on_handle,
                run_id=run_id,
            )
            # Do not downgrade a run the user already cancelled.
            if state.run.status != TrainRunStatus.cancelled:
                state.run.status = status
        except Exception as exc:  # noqa: BLE001
            if state.run.status != TrainRunStatus.cancelled:
                state.run.status = TrainRunStatus.failed
            state.error = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=_worker, name=f"run-{run_id}", daemon=True)
    state.thread = thread
    state.run.status = TrainRunStatus.running
    thread.start()


class EvalRequest(BaseModel):
    """Body for ``POST /api/runs/{id}/eval``."""

    split: str = "test"


@router.post("/{run_id}/eval")
def eval_run(run_id: str, body: EvalRequest | None = None) -> dict[str, Any]:
    """Launch eval_only on the run's best skill against ``body.split``."""
    split = (body.split if body else None) or "test"
    state = _get(run_id)
    run_dir = Path(state.run.run_dir or "")
    best = None
    for cand in (run_dir / "best_skill.md", run_dir / "skills" / "best_skill.md"):
        if cand.is_file():
            best = cand
            break
    if best is None:
        raise HTTPException(status_code=409, detail="no best_skill.md yet for this run")

    cfg_path = config.CONFIGS_DIR / "generic_qa" / f"{state.run.slug}.yaml"
    if not cfg_path.is_file():
        raise HTTPException(status_code=409, detail=f"run config not found: {cfg_path}")

    argv = args_mod.build_eval_argv(
        config_path=cfg_path,
        skill_path=best,
        skillopt_clone_dir=config.SKILLOPT_CLONE_DIR,
        split=split,
        python_executable=str(config.VENV_PYTHON) if config.VENV_PYTHON.exists() else None,
    )
    env = _build_role_env(state.run.model_config_)
    eval_run_id = f"{run_id}-eval"
    eval_state = _RunState(
        TrainRun(
            id=eval_run_id,
            slug=f"{state.run.slug}-eval",
            skill_id=state.run.skill_id,
            dataset_name=state.run.dataset_name,
            model_config=state.run.model_config_,
            run_dir=state.run.run_dir,
        )
    )
    with _RUNS_LOCK:
        _RUNS[eval_run_id] = eval_state
    _launch(eval_state, argv, env, eval_run_id)
    return {"id": eval_run_id, "status": "running", "split": split}


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str) -> dict[str, Any]:
    """SIGTERM the run's process group."""
    state = _get(run_id)
    if state.handle is None:
        raise HTTPException(status_code=409, detail="run has no live process")
    ok = state.handle.cancel()
    if ok:
        state.run.status = TrainRunStatus.cancelled
    return {"id": run_id, "cancelled": ok, "status": state.run.status.value}


@router.get("")
def list_runs() -> dict[str, Any]:
    """List all known runs (most recent first)."""
    with _RUNS_LOCK:
        runs = list(_RUNS.values())
    runs.sort(key=lambda s: s.run.created_at, reverse=True)
    return {
        "runs": [
            {
                "id": s.run.id,
                "slug": s.run.slug,
                "status": s.run.status.value,
                "dataset_name": s.run.dataset_name,
                "run_dir": s.run.run_dir,
                "created_at": s.run.created_at.isoformat(),
                "error": s.error,
            }
            for s in runs
        ]
    }


@router.get("/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Return run status plus parsed outputs (partial reconstruction on failure)."""
    state = _get(run_id)
    run = state.run
    payload: dict[str, Any] = {
        "id": run.id,
        "slug": run.slug,
        "status": run.status.value,
        "run_dir": run.run_dir,
        "error": state.error,
    }

    run_dir = run.run_dir
    if run_dir and Path(run_dir).is_dir():
        if run.status == TrainRunStatus.failed:
            payload["partial"] = recovery.reconstruct_partial(
                run_dir, error_message=state.error or "", exit_code=None
            )
        else:
            try:
                parsed = outputs.parse_run_tree(run_dir)
                payload["outputs"] = parsed.to_dict()
            except Exception as exc:  # noqa: BLE001
                payload["outputs"] = None
                payload["outputs_error"] = str(exc)
    return payload


@router.get("/{run_id}/versions")
def get_run_versions(run_id: str) -> dict[str, Any]:
    """Return the per-step SkillVersion list parsed from the run tree.

    Each version: ``{step, md_text, is_best}``. Reads ``skills/skill_v####.md``
    snapshots (+ best_skill.md) via ``outputs.parse_run_tree``."""
    state = _get(run_id)
    run_dir = state.run.run_dir
    if not run_dir or not Path(run_dir).is_dir():
        return {"id": run_id, "versions": []}
    try:
        parsed = outputs.parse_run_tree(run_dir)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=409, detail=f"run outputs not parseable yet: {exc}") from exc

    versions: list[dict[str, Any]] = []
    for sv in parsed.skill_versions:
        md_text = ""
        try:
            md_text = Path(sv["path"]).read_text(encoding="utf-8")
        except (OSError, KeyError):
            md_text = ""
        versions.append({"step": sv.get("step"), "md_text": md_text, "is_best": bool(sv.get("is_best"))})
    # Append best_skill.md as a synthetic best version if not already covered.
    if parsed.best_skill_text and not any(v["is_best"] for v in versions):
        versions.append({"step": -1, "md_text": parsed.best_skill_text, "is_best": True})
    return {"id": run_id, "versions": versions}


@router.get("/{run_id}/scores")
def get_run_scores(run_id: str) -> dict[str, Any]:
    """Return the ScorePoint list (evolution curve) parsed from the run tree.

    Each point: ``{step, epoch, train_score, sel_score, accepted}``."""
    state = _get(run_id)
    run_dir = state.run.run_dir
    if not run_dir or not Path(run_dir).is_dir():
        return {"id": run_id, "scores": []}
    try:
        parsed = outputs.parse_run_tree(run_dir)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=409, detail=f"run outputs not parseable yet: {exc}") from exc
    return {
        "id": run_id,
        "scores": [p.to_dict() for p in parsed.score_series],
        "final_test_score": parsed.final_test_score,
    }


def _get(run_id: str) -> _RunState:
    with _RUNS_LOCK:
        state = _RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return state


__all__ = ["router"]
