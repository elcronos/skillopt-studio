"""Tests for the module-level ``grading.score`` adapter (env↔grading bridge).

The generic_qa env calls ``grading.score(scoring_type=..., prediction=...,
ground_truth=..., ...)``. This must:
- work for the deterministic graders (f1/exact/fuzzy);
- normalize list/dict ground_truth shapes the env may pass;
- dispatch llm_judge through the injected model_call (NOT silently f1);
- dispatch custom_python through the sandbox (NOT silently f1).
"""

from __future__ import annotations

import pytest

from skillopt_studio import grading
from skillopt_studio.grading import _coerce_ground_truth


class TestScoreAdapterDeterministic:
    def test_f1_works(self):
        s = grading.score(scoring_type="f1", prediction="the quick brown fox",
                          ground_truth="the quick brown fox")
        assert s == pytest.approx(1.0)

    def test_exact_works(self):
        s = grading.score(scoring_type="exact", prediction="Paris", ground_truth="paris")
        assert s == 1.0

    def test_clamped(self):
        s = grading.score(scoring_type="f1", prediction="x", ground_truth="y")
        assert 0.0 <= s <= 1.0

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            grading.score(scoring_type="bogus", prediction="a", ground_truth="b")


class TestGroundTruthNormalization:
    def test_list_picks_first(self):
        assert _coerce_ground_truth(["alpha", "beta"]) == "alpha"

    def test_dict_answer(self):
        assert _coerce_ground_truth({"answer": "x"}) == "x"

    def test_dict_answers_list(self):
        assert _coerce_ground_truth({"answers": ["a", "b"]}) == "a"

    def test_adapter_handles_list_ground_truth(self):
        # f1 against a list gold: env passes the raw list; adapter normalizes it.
        s = grading.score(scoring_type="f1", prediction="paris",
                          ground_truth=["paris", "france"])
        assert s == pytest.approx(1.0)


class TestJudgeDispatchNotF1:
    def test_llm_judge_uses_model_call(self):
        calls: list[tuple[str, str]] = []

        def fake_judge(prompt: str, model: str) -> str:
            calls.append((prompt, model))
            return "0.0"  # judge says wrong; f1 would say 1.0 for identical text

        # prediction == ground_truth → f1 would be 1.0. The judge returns 0.0, so
        # a result of 0.0 proves the judge path ran and f1 fallback did NOT.
        s = grading.score(
            scoring_type="llm_judge",
            prediction="the same text",
            ground_truth="the same text",
            rubric="Is it correct?",
            judge_model="judge-x",
            model_call=fake_judge,
        )
        assert s == 0.0
        assert calls, "model_call was never invoked — llm_judge silently fell back"
        assert calls[0][1] == "judge-x"

    def test_llm_judge_without_model_call_raises(self):
        # No silent f1 fallback: a misconfigured llm_judge surfaces loudly.
        with pytest.raises(ValueError):
            grading.score(
                scoring_type="llm_judge",
                prediction="x",
                ground_truth="x",
                rubric="r",
            )


class TestCustomPythonDispatchNotF1:
    def test_custom_python_runs_sandbox_not_f1(self):
        # A custom scorer that always returns 0.3. f1 of identical text is 1.0, so
        # a 0.3 result proves the sandbox ran and f1 fallback did NOT.
        code = (
            "def score(prediction, ground_truth, item=None):\n"
            "    return 0.3\n"
        )
        s = grading.score(
            scoring_type="custom_python",
            prediction="identical",
            ground_truth="identical",
            custom_code=code,
            custom_consent=True,
        )
        assert s == pytest.approx(0.3)
