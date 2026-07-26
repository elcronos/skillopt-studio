"""Shared pydantic v2 domain models.

Every other backend package imports from this module. Models are intentionally
plain and well-defaulted so they serialize cleanly to JSON for the REST API and
SSE stream. Field semantics are anchored to the verified SkillOpt contract
(see ``SKILLOPT_INTEGRATION.md``): scores carry ``hard`` (int 0/1) and ``soft``
(float 0..1); the stdout stream is the authoritative live signal.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class ProviderName(str, Enum):
    """Where a skill was discovered."""

    claude = "claude"
    codex = "codex"
    openai = "openai"
    cwd = "cwd"


class GraderType(str, Enum):
    """How a rollout's answer is scored into ``soft`` (float 0..1)."""

    exact = "exact"
    fuzzy = "fuzzy"
    f1 = "f1"
    llm_judge = "llm_judge"
    geval = "geval"
    custom_python = "custom_python"


class TrainRunStatus(str, Enum):
    """Lifecycle of a training run."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
class Skill(BaseModel):
    """A skill discovered by a provider scanner.

    ``id`` is a stable studio-assigned identifier (e.g. ``"<provider>:<slug>"``);
    ``source_path`` is the absolute path to the skill's defining ``.md`` file.
    """

    id: str
    name: str
    provider: ProviderName
    source_path: str
    body: str = Field(default="", description="Full markdown body of the skill.")


class SkillVersion(BaseModel):
    """A snapshot of the skill at a given optimization step."""

    step: int
    md_text: str
    is_best: bool = False


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
class DatasetCase(BaseModel):
    """One evaluation case. Mirrors SkillOpt's dataloader item shape
    (``id``/``input``/``ground_truth``/``metadata``)."""

    id: str
    input: str
    ground_truth: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Dataset(BaseModel):
    """A self-contained dataset for the generic_qa adapter.

    ``split_mode`` follows SkillOpt: ``"ratio"`` derives a deterministic split
    from the data, ``"split_dir"`` uses pre-split directories. ``split_ratio`` is
    a colon string like ``"2:1:7"`` (train:valid:test) when ``split_mode`` is
    ``"ratio"``.
    """

    name: str
    cases: list[DatasetCase] = Field(default_factory=list)
    split_mode: Literal["ratio", "split_dir"] = "ratio"
    split_ratio: str = "2:1:7"


# ---------------------------------------------------------------------------
# Grader configuration
# ---------------------------------------------------------------------------
class GraderConfig(BaseModel):
    """Scoring spec applied to each rollout.

    ``threshold`` converts ``soft`` → ``hard`` (``hard = int(soft >= threshold)``).
    ``rubric``/``judge_model`` apply to ``llm_judge``; ``criteria``/
    ``evaluation_steps``/``judge_model`` apply to ``geval`` (DeepEval G-Eval);
    ``custom_code``/``custom_consent`` to ``custom_python`` (run in the
    honest-mistake sandbox).
    """

    type: GraderType = GraderType.exact
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    rubric: Optional[str] = None
    judge_model: Optional[str] = None
    custom_code: Optional[str] = None

    # --- geval (DeepEval G-Eval) -------------------------------------------
    # Exactly one of ``criteria`` (free-text) or ``evaluation_steps`` (explicit
    # ordered steps) should be supplied; DeepEval derives steps from criteria if
    # only ``criteria`` is given. The judge is pinned at temperature 0.
    criteria: Optional[str] = None
    evaluation_steps: Optional[list[str]] = None
    # Self-consistency: average over N independent judge calls (N>=1). Higher N
    # reduces judge noise that SkillOpt warns confuses the optimizer.
    self_consistency: int = Field(default=1, ge=1, le=10)

    # --- custom_python sandbox consent -------------------------------------
    # Running user Python requires explicit opt-in. The sandbox is honest-mistake
    # containment, NOT adversarial isolation (see grading/sandbox.py).
    custom_consent: bool = False


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
class ModelConfig(BaseModel):
    """Backend + model selection for a run.

    ``backend`` is a SkillOpt backend key (e.g. ``openai_chat``,
    ``openai_compatible``, ``claude_chat``, ``qwen_chat``, ``minimax_chat``).
    These map to YAML ``model.*`` keys at config-generation time. Secrets are NOT
    stored here — they live in the OS keyring and are injected via env.
    """

    backend: str = "openai_chat"
    optimizer_model: str = "gpt-5.5"
    target_model: str = "gpt-5.5"
    optimizer_backend: Optional[str] = None  # defaults to ``backend`` if unset
    target_backend: Optional[str] = None     # defaults to ``backend`` if unset
    endpoint: Optional[str] = None
    api_version: Optional[str] = None
    reasoning_effort: str = "medium"


# ---------------------------------------------------------------------------
# Training runs
# ---------------------------------------------------------------------------
class TrainRun(BaseModel):
    """A single optimization run wrapping ``scripts/train.py``."""

    id: str
    slug: str
    skill_id: str
    dataset_name: str
    model_config_: ModelConfig = Field(
        default_factory=ModelConfig,
        alias="model_config",
        description="Model/backend selection for this run.",
    )
    status: TrainRunStatus = TrainRunStatus.pending
    run_dir: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

    # ``model_config`` is reserved by pydantic v2 for class settings, so the field
    # is stored as ``model_config_`` but exposed via the ``model_config`` alias.
    model_config = {"populate_by_name": True}


class ScorePoint(BaseModel):
    """One point on the evolution curve at a step boundary.

    ``train_score`` is the rollout/minibatch score; ``sel_score`` is the
    validation (selection) gate score; ``accepted`` reflects the gate decision.
    """

    step: int
    epoch: int = 0
    train_score: Optional[float] = None
    sel_score: Optional[float] = None
    accepted: Optional[bool] = None


# ---------------------------------------------------------------------------
# SSE events (stdout-authoritative live stream)
# ---------------------------------------------------------------------------
class StepEvent(BaseModel):
    """A ``[STEP x/y]`` boundary, optionally carrying reconciled scores."""

    type: Literal["step"] = "step"
    step: int
    total_steps: Optional[int] = None
    train_score: Optional[float] = None
    sel_score: Optional[float] = None
    accepted: Optional[bool] = None


class EpochEvent(BaseModel):
    """An ``[EPOCH x/y]`` boundary."""

    type: Literal["epoch"] = "epoch"
    epoch: int
    total_epochs: Optional[int] = None


class StageEvent(BaseModel):
    """A per-step stage marker (e.g. ``1/6 rollout``, ``4/6 select``, ``6/6 gate``)."""

    type: Literal["stage"] = "stage"
    step: Optional[int] = None
    stage: str
    index: Optional[int] = None   # e.g. 1..6
    total: Optional[int] = None   # e.g. 6


class ErrorEvent(BaseModel):
    """An error surfaced from the run. ``recoverable`` indicates whether the run
    can continue (e.g. a single rollout failed) or has terminated."""

    type: Literal["error"] = "error"
    step: Optional[int] = None
    message: str
    recoverable: bool = False


class LogEvent(BaseModel):
    """A raw stdout line from a subprocess stage, tagged with its stage name.

    Used by the LangGraph-conversion pipeline (and any multi-stage subprocess
    driver) to stream live per-line output without forcing it through the
    score-oriented Step/Stage markers."""

    type: Literal["log"] = "log"
    stage: str
    line: str


class DoneEvent(BaseModel):
    """Terminal event. ``status`` is the final run status; ``best_skill_path`` and
    held-out scores are populated on success."""

    type: Literal["done"] = "done"
    status: TrainRunStatus
    best_skill_path: Optional[str] = None
    final_test_score: Optional[float] = None


# Discriminated union of all SSE event payloads.
SSEEvent = Union[StepEvent, EpochEvent, StageEvent, LogEvent, ErrorEvent, DoneEvent]


__all__ = [
    "ProviderName",
    "GraderType",
    "TrainRunStatus",
    "Skill",
    "SkillVersion",
    "DatasetCase",
    "Dataset",
    "GraderConfig",
    "ModelConfig",
    "TrainRun",
    "ScorePoint",
    "StepEvent",
    "EpochEvent",
    "StageEvent",
    "LogEvent",
    "ErrorEvent",
    "DoneEvent",
    "SSEEvent",
]
