"""The bundled tutorial example must always stay loadable + schema-valid.

Guards the date-normalizer example (skill.md + dataset.json + grader.json) that
TUTORIAL.md walks through, so a schema change can never silently break the
first-run experience.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillopt_studio.domain import GraderConfig, GraderType
from skillopt_studio.dataset.models import DatasetCreate

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "date-normalizer"


def test_example_files_exist() -> None:
    for fname in ("skill.md", "dataset.json", "grader.json"):
        assert (EXAMPLE / fname).is_file(), f"missing example file: {fname}"


def test_example_skill_has_frontmatter_and_body() -> None:
    text = (EXAMPLE / "skill.md").read_text(encoding="utf-8")
    assert text.startswith("---"), "skill.md should open with YAML frontmatter"
    assert "name: date-normalizer" in text
    assert "ISO 8601" in text or "YYYY-MM-DD" in text


def test_example_dataset_loads_into_model() -> None:
    raw = json.loads((EXAMPLE / "dataset.json").read_text(encoding="utf-8"))
    ds = DatasetCreate.model_validate(raw)
    assert ds.name
    assert len(ds.cases) >= 12, "need enough cases to split train/valid/test"
    # every case is a real eval: input + canonical ISO ground truth
    for c in ds.cases:
        assert c.input.strip()
        assert len(c.ground_truth) == 10 and c.ground_truth[4] == "-" and c.ground_truth[7] == "-", (
            f"case {c.id} ground_truth is not YYYY-MM-DD: {c.ground_truth!r}"
        )
    # split ratio parses to three positive parts (train:valid:test)
    parts = [int(p) for p in ds.split_ratio.split(":")]
    assert len(parts) == 3 and all(p > 0 for p in parts)


def test_example_grader_is_valid_exact() -> None:
    raw = json.loads((EXAMPLE / "grader.json").read_text(encoding="utf-8"))
    # strip doc-only keys before validating against the real model
    cfg = GraderConfig.model_validate({k: v for k, v in raw.items() if not k.startswith("_")})
    assert cfg.type is GraderType.exact
    assert 0.0 <= cfg.threshold <= 1.0


def test_example_case_ids_are_unique() -> None:
    raw = json.loads((EXAMPLE / "dataset.json").read_text(encoding="utf-8"))
    ids = [c["id"] for c in raw["cases"]]
    assert len(ids) == len(set(ids)), "duplicate case ids in example dataset"
