"""Tests that the generic_qa env dispatches non-f1 graders correctly.

Asserts:
- f1 (built-in) works end-to-end through ``_score``;
- llm_judge routes through the bound judge model_call (NOT the f1 fallback),
  with the judge mocked;
- custom_python routes through the sandbox (NOT the f1 fallback).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the studio env importable (it lives outside the backend package).
_ENVS = str(Path(__file__).resolve().parents[2] / "skillopt_studio_envs")
if _ENVS not in sys.path:
    sys.path.insert(0, _ENVS)

import generic_qa.env as env_mod  # noqa: E402
from generic_qa.env import GenericQAEnv  # noqa: E402


def _make_env(scoring: dict, data_path: str) -> GenericQAEnv:
    return GenericQAEnv(data_path=data_path, scoring=scoring)


@pytest.fixture()
def dataset_file(tmp_path: Path) -> str:
    import json

    p = tmp_path / "dataset.json"
    p.write_text(json.dumps([{"id": "1", "input": "q", "ground_truth": "paris"}]), encoding="utf-8")
    return str(p)


class TestF1Builtin:
    def test_f1_inline(self, dataset_file):
        e = _make_env({"type": "f1", "threshold": 0.5}, dataset_file)
        item = {"id": "1", "input": "q", "ground_truth": "paris"}
        assert e._score(item, "paris", "paris") == pytest.approx(1.0)


class TestLLMJudgeNotF1:
    def test_judge_path_used(self, dataset_file, monkeypatch):
        # Mock SkillOpt's chat_target so the bound judge model_call returns 0.0.
        # prediction == gold → f1 fallback would be 1.0; a 0.0 result proves the
        # judge ran instead.
        seen = {"called": False}

        def fake_chat_target(*, system, user, **kw):
            seen["called"] = True
            return "0.0", {}

        monkeypatch.setattr(env_mod, "chat_target", fake_chat_target)
        e = _make_env(
            {"type": "llm_judge", "threshold": 0.5, "rubric": "ok?", "judge_model": "j"},
            dataset_file,
        )
        item = {"id": "1", "input": "q", "ground_truth": "paris"}
        score = e._score(item, "paris", "paris")
        assert seen["called"], "judge model_call never ran (silent f1 fallback)"
        assert score == 0.0


class TestCustomPythonNotF1:
    def test_sandbox_path_used(self, dataset_file):
        code = "def score(prediction, ground_truth, item=None):\n    return 0.25\n"
        e = _make_env(
            {"type": "custom_python", "threshold": 0.5},
            dataset_file,
        )
        # Inject the code as if loaded from the sidecar path.
        e.custom_python = code
        item = {"id": "1", "input": "q", "ground_truth": "paris"}
        # f1 of identical text would be 1.0; 0.25 proves the sandbox scorer ran.
        score = e._score(item, "paris", "paris")
        assert score == pytest.approx(0.25)
