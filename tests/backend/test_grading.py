"""Tests for the grading subsystem.

Covers: exact/fuzzy/f1 correctness, the universal [0,1] clamp, the custom-python
sandbox (runs, scrubs env, enforces timeout, honors consent), the metric
recommender, and a guarded/skipped geval test.
"""

from __future__ import annotations

import pytest

from skillopt_studio.domain import Dataset, DatasetCase, GraderConfig, GraderType
from skillopt_studio.grading import make_grader, recommend_grader, estimate_judge_calls
from skillopt_studio.grading.base import clamp
from skillopt_studio.grading.geval import deepeval_available


# ---------------------------------------------------------------------------
# Deterministic graders
# ---------------------------------------------------------------------------
class TestExact:
    def test_exact_match(self):
        g = make_grader(GraderConfig(type=GraderType.exact))
        assert g.score("Paris", "paris") == 1.0  # normalized
        assert g.score("  Paris ", "Paris") == 1.0
        assert g.score("London", "Paris") == 0.0

    def test_clamped_range(self):
        g = make_grader(GraderConfig(type=GraderType.exact))
        assert 0.0 <= g.score("x", "y") <= 1.0


class TestFuzzy:
    def test_identical_is_one(self):
        g = make_grader(GraderConfig(type=GraderType.fuzzy))
        assert g.score("hello world", "hello world") == 1.0

    def test_partial_between_zero_and_one(self):
        g = make_grader(GraderConfig(type=GraderType.fuzzy))
        s = g.score("hello world", "hello werld")
        assert 0.0 < s < 1.0

    def test_both_empty_is_one(self):
        g = make_grader(GraderConfig(type=GraderType.fuzzy))
        assert g.score("", "") == 1.0


class TestF1:
    def test_perfect_overlap(self):
        g = make_grader(GraderConfig(type=GraderType.f1))
        assert g.score("the quick brown fox", "the quick brown fox") == 1.0

    def test_partial_overlap(self):
        g = make_grader(GraderConfig(type=GraderType.f1))
        # pred tokens {the, cat}, truth {the, dog} -> overlap 1
        # precision 1/2, recall 1/2 -> f1 0.5
        assert g.score("the cat", "the dog") == pytest.approx(0.5)

    def test_no_overlap(self):
        g = make_grader(GraderConfig(type=GraderType.f1))
        assert g.score("alpha beta", "gamma delta") == 0.0

    def test_punctuation_ignored(self):
        g = make_grader(GraderConfig(type=GraderType.f1))
        assert g.score("Hello, world!", "hello world") == 1.0

    def test_multiplicity(self):
        g = make_grader(GraderConfig(type=GraderType.f1))
        # pred {a a}, truth {a} -> overlap 1, precision 1/2, recall 1/1 -> 2/3
        assert g.score("a a", "a") == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Clamp
# ---------------------------------------------------------------------------
class TestClamp:
    def test_clamp_bounds(self):
        assert clamp(-5.0) == 0.0
        assert clamp(5.0) == 1.0
        assert clamp(0.5) == 0.5

    def test_clamp_nan_and_garbage(self):
        assert clamp(float("nan")) == 0.0
        assert clamp("not a number") == 0.0  # type: ignore[arg-type]
        assert clamp(None) == 0.0  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Custom-python sandbox
# ---------------------------------------------------------------------------
class TestCustomSandbox:
    def test_requires_consent(self):
        g = make_grader(
            GraderConfig(
                type=GraderType.custom_python,
                custom_code="def score(p, gt, item=None):\n    return 1.0\n",
                custom_consent=False,
            )
        )
        assert g.score("a", "a") == 0.0  # no consent -> disabled

    def test_runs_with_consent(self):
        g = make_grader(
            GraderConfig(
                type=GraderType.custom_python,
                custom_code=(
                    "def score(p, gt, item=None):\n"
                    "    return 1.0 if p == gt else 0.0\n"
                ),
                custom_consent=True,
            )
        )
        assert g.score("same", "same") == 1.0
        assert g.score("a", "b") == 0.0

    def test_score_is_clamped(self):
        g = make_grader(
            GraderConfig(
                type=GraderType.custom_python,
                custom_code="def score(p, gt, item=None):\n    return 99.0\n",
                custom_consent=True,
            )
        )
        assert g.score("x", "y") == 1.0

    def test_env_is_scrubbed(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-should-not-leak")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")
        g = make_grader(
            GraderConfig(
                type=GraderType.custom_python,
                custom_code=(
                    "import os\n"
                    "def score(p, gt, item=None):\n"
                    "    leaked = any('API_KEY' in k for k in os.environ)\n"
                    "    return 1.0 if leaked else 0.0\n"
                ),
                custom_consent=True,
            )
        )
        # 0.0 => no API_KEY var visible in the child env.
        assert g.score("x", "y") == 0.0

    def test_timeout_enforced(self):
        from skillopt_studio.grading.custom import CustomPythonGrader

        g = CustomPythonGrader(
            GraderConfig(
                type=GraderType.custom_python,
                custom_code=(
                    "import time\n"
                    "def score(p, gt, item=None):\n"
                    "    time.sleep(30)\n"
                    "    return 1.0\n"
                ),
                custom_consent=True,
            ),
            timeout=2,
        )
        # Times out -> failure -> 0.0 (and well under the 30s sleep).
        assert g.score("x", "y") == 0.0

    def test_no_code_scores_zero(self):
        g = make_grader(
            GraderConfig(type=GraderType.custom_python, custom_consent=True)
        )
        assert g.score("x", "y") == 0.0


# ---------------------------------------------------------------------------
# llm_judge (injected model-call fn, no network)
# ---------------------------------------------------------------------------
class TestLLMJudge:
    def test_parses_bare_float(self):
        from skillopt_studio.grading.base import make_grader as mg

        g = mg(
            GraderConfig(type=GraderType.llm_judge, rubric="r", judge_model="m"),
            model_call=lambda prompt, model: "0.8",
        )
        assert g.score("p", "gt") == pytest.approx(0.8)

    def test_parses_scale_and_clamps(self):
        from skillopt_studio.grading.base import make_grader as mg

        g = mg(
            GraderConfig(type=GraderType.llm_judge),
            model_call=lambda prompt, model: "85",
        )
        assert g.score("p", "gt") == pytest.approx(0.85)

    def test_judge_failure_scores_zero(self):
        from skillopt_studio.grading.base import make_grader as mg

        def boom(prompt, model):
            raise RuntimeError("judge down")

        g = mg(GraderConfig(type=GraderType.llm_judge), model_call=boom)
        assert g.score("p", "gt") == 0.0

    def test_requires_model_call(self):
        with pytest.raises(ValueError):
            make_grader(GraderConfig(type=GraderType.llm_judge))


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------
class TestRecommender:
    def _ds(self, truths: list[str]) -> Dataset:
        return Dataset(
            name="t",
            cases=[DatasetCase(id=str(i), input="q", ground_truth=g) for i, g in enumerate(truths)],
        )

    def test_single_token_recommends_exact(self):
        rec = recommend_grader(self._ds(["yes", "no", "blue"]))
        assert rec["type"] == GraderType.exact.value

    def test_short_phrase_recommends_f1(self):
        rec = recommend_grader(self._ds(["the eiffel tower", "mount everest peak"]))
        assert rec["type"] == GraderType.f1.value

    def test_long_freetext_recommends_geval(self):
        long = "This is a long multi-sentence answer. It explains reasoning. It concludes."
        rec = recommend_grader(self._ds([long, long]))
        assert rec["type"] == GraderType.geval.value

    def test_structured_recommends_exact(self):
        rec = recommend_grader(self._ds(['{"a": 1}', '{"b": 2}']))
        assert rec["type"] == GraderType.exact.value

    def test_no_ground_truth_recommends_geval(self):
        rec = recommend_grader(self._ds(["", ""]))
        assert rec["type"] == GraderType.geval.value

    def test_estimate_judge_calls(self):
        ds = self._ds(["a", "b", "c", "d"])
        est = estimate_judge_calls(ds, {"num_steps": 3, "self_consistency": 2})
        assert est["calls"] == 3 * 4 * 2
        assert "judge calls" in est["note"]


# ---------------------------------------------------------------------------
# geval (guarded / skipped when deepeval absent)
# ---------------------------------------------------------------------------
class TestGEval:
    def test_construct_never_crashes(self):
        # Building the grader must work regardless of deepeval presence.
        g = make_grader(
            GraderConfig(type=GraderType.geval, criteria="is it correct", judge_model="m")
        )
        assert g is not None

    def test_disabled_when_deepeval_absent(self):
        if deepeval_available():
            pytest.skip("deepeval installed; disabled-path test not applicable")
        g = make_grader(GraderConfig(type=GraderType.geval, criteria="c"))
        # Disabled grader returns 0.0 without crashing.
        assert g.score("pred", "gt") == 0.0

    @pytest.mark.skipif(not deepeval_available(), reason="deepeval not installed")
    def test_metadata_reports_judge(self):
        from skillopt_studio.grading.geval import GEvalGrader

        g = GEvalGrader(GraderConfig(type=GraderType.geval, criteria="c", judge_model="gpt-4o-mini"))
        meta = g.metadata()
        assert meta["judge_model"] == "gpt-4o-mini"
        assert meta["grader"] == "geval"
