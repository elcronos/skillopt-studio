"""Filesystem-backed dataset CRUD.

Each dataset lives under ``<datasets_dir>/<slug>/`` and is self-contained:

- ``dataset.json`` — the canonical SkillOpt-shaped payload: a top-level object
  with ``split_mode`` / ``split_ratio`` plus ``cases`` = a list of
  ``{"id","input","ground_truth","metadata"}``. The generic_qa loader reads the
  ``cases`` list directly.
- on request (``split_mode == "split_dir"``) the store also emits a
  ``split_dir/{train,valid,test}.json`` layout (each a list of ``{"id": ...}``)
  matching SkillOpt's ``split_dir`` convention.

The store is defensive: a corrupt or missing dataset surfaces as "not found"
rather than an exception, mirroring the scanner package's graceful contract.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from .. import config
from ..domain import Dataset, DatasetCase
from .models import DatasetSummary

logger = logging.getLogger("skillopt_studio.dataset")

# Datasets root: ``<repo>/configs/datasets`` keeps user data alongside the
# generated generic_qa configs without colliding with run outputs.
DATASETS_DIR: Path = config.CONFIGS_DIR / "datasets"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Turn a dataset name into a filesystem-safe slug."""
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "dataset"


def _dataset_dir(slug: str) -> Path:
    return DATASETS_DIR / slug


def _dataset_json(slug: str) -> Path:
    return _dataset_dir(slug) / "dataset.json"


def _ensure_root() -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)


def _write_split_dir(slug: str, cases: list[DatasetCase], split_ratio: str) -> Path:
    """Emit a ``split_dir/{train,valid,test}.json`` layout (lists of ``{"id": ...}``).

    Splits are deterministic by case order using the colon ratio (train:valid:test).
    """
    split_root = _dataset_dir(slug) / "split_dir"
    split_root.mkdir(parents=True, exist_ok=True)
    try:
        parts = [int(p) for p in split_ratio.split(":")]
        if len(parts) != 3 or sum(parts) <= 0:
            raise ValueError
    except Exception:  # noqa: BLE001 - bad ratio degrades to all-train
        parts = [1, 0, 0]

    total = sum(parts)
    n = len(cases)
    n_train = n * parts[0] // total
    n_valid = n * parts[1] // total
    buckets = {
        "train": cases[:n_train],
        "valid": cases[n_train : n_train + n_valid],
        "test": cases[n_train + n_valid :],
    }
    for split_name, bucket in buckets.items():
        payload = [{"id": c.id} for c in bucket]
        (split_root / f"{split_name}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return split_root


def create(dataset: Dataset) -> DatasetSummary:
    """Persist ``dataset`` as a self-contained ``dataset.json`` and return a summary.

    Overwrites an existing dataset with the same slug. When
    ``split_mode == "split_dir"`` a ``split_dir/`` layout is also emitted.
    """
    _ensure_root()
    slug = _slugify(dataset.name)
    ddir = _dataset_dir(slug)
    ddir.mkdir(parents=True, exist_ok=True)

    payload = {
        "name": dataset.name,
        "split_mode": dataset.split_mode,
        "split_ratio": dataset.split_ratio,
        "cases": [c.model_dump() for c in dataset.cases],
    }
    _dataset_json(slug).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if dataset.split_mode == "split_dir":
        _write_split_dir(slug, dataset.cases, dataset.split_ratio)

    logger.info("created dataset '%s' (%d cases)", slug, len(dataset.cases))
    return DatasetSummary(
        name=dataset.name,
        num_cases=len(dataset.cases),
        split_mode=dataset.split_mode,
        split_ratio=dataset.split_ratio,
        path=str(_dataset_json(slug)),
    )


def get(name: str) -> Optional[Dataset]:
    """Load a dataset by name (or slug). Returns None if absent/corrupt."""
    slug = _slugify(name)
    path = _dataset_json(slug)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("dataset '%s' unreadable; reporting not found", slug)
        return None
    cases = [DatasetCase(**c) for c in raw.get("cases", []) if isinstance(c, dict)]
    return Dataset(
        name=raw.get("name", name),
        cases=cases,
        split_mode=raw.get("split_mode", "ratio"),
        split_ratio=raw.get("split_ratio", "2:1:7"),
    )


def list_datasets() -> list[DatasetSummary]:
    """Return summaries for every dataset under the datasets root."""
    if not DATASETS_DIR.exists():
        return []
    summaries: list[DatasetSummary] = []
    for child in sorted(DATASETS_DIR.iterdir()):
        if not child.is_dir():
            continue
        ds = get(child.name)
        if ds is None:
            continue
        summaries.append(
            DatasetSummary(
                name=ds.name,
                num_cases=len(ds.cases),
                split_mode=ds.split_mode,
                split_ratio=ds.split_ratio,
                path=str(_dataset_json(child.name)),
            )
        )
    return summaries


def delete(name: str) -> bool:
    """Delete a dataset directory. Returns True if it existed."""
    slug = _slugify(name)
    ddir = _dataset_dir(slug)
    if not ddir.exists():
        return False
    shutil.rmtree(ddir, ignore_errors=True)
    logger.info("deleted dataset '%s'", slug)
    return True


def data_path(name: str) -> Optional[Path]:
    """Return the ``dataset.json`` path for a dataset (for config generation)."""
    slug = _slugify(name)
    path = _dataset_json(slug)
    return path if path.exists() else None


__all__ = [
    "DATASETS_DIR",
    "create",
    "get",
    "list_datasets",
    "delete",
    "data_path",
]
