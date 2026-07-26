"""Generic single-turn QA environment adapter for SkillOpt.

This is the REUSABLE adapter that lets SkillOpt Studio optimize *any* skill,
not just the bundled benchmarks. It implements the REAL ``EnvAdapter`` interface
verified from ``skillopt/envs/base.py`` and modeled on
``skillopt/envs/searchqa/adapter.py`` — i.e. ``build_train_env`` /
``build_eval_env`` / ``rollout`` / ``reflect`` / ``get_task_types`` — NOT the
simplified ``execute``/``evaluate`` shape from the (aspirational) docs.

Pipeline contract (verified):
- The trainer instantiates the adapter via ``scripts/train.py::get_adapter`` which
  inspects ``__init__`` and passes only matching keys from the FLATTENED config.
  So every constructor kwarg below must be a flat config key (e.g. ``data_path``,
  ``minibatch_size``, ``analyst_workers``, ``exec_timeout``, ``edit_budget`` —
  note SkillOpt maps ``optimizer.learning_rate``→``edit_budget`` during flatten).
- ``rollout(env_manager, skill_content, out_dir, **kw)`` returns a list of dicts
  each with at least ``{"id", "hard": int(0/1), "soft": float}``. We also persist
  ``predictions/<id>/conversation.json`` and a ``results.jsonl`` so the shared
  reflect engine (``fmt_minibatch_trajectories``) can read trajectories.
- ``reflect(...)`` delegates to ``skillopt.gradient.reflect.run_minibatch_reflect``
  with the exact verified signature — we do NOT reinvent reflection.

Scoring is driven by a SCORING SPEC read from the flattened config under the
``scoring`` key (or flat ``scoring_*`` keys). Soft score is a float in [0,1];
``hard = int(soft >= threshold)``. The actual grader implementations may live in
the backend ``grading/`` package (built by another agent); we import them
DEFENSIVELY and fall back to self-contained exact/fuzzy/f1 scorers when that
module is unavailable in the env's runtime.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

# ── SkillOpt imports (defensive so py_compile / unit import works standalone) ──
try:
    from skillopt.envs.base import EnvAdapter
except Exception:  # pragma: no cover
    class EnvAdapter:  # type: ignore[no-redef]
        """Fallback stub so this module imports without skillopt installed."""

        def setup(self, cfg: dict) -> None:
            self._cfg = dict(cfg)

        def get_error_minibatch_prompt(self):  # noqa: D401
            return None

        def get_success_minibatch_prompt(self):  # noqa: D401
            return None

try:
    from skillopt.gradient.reflect import run_minibatch_reflect
except Exception:  # pragma: no cover
    run_minibatch_reflect = None  # type: ignore[assignment]

try:
    from skillopt.model import chat_target, is_target_exec_backend
except Exception:  # pragma: no cover
    chat_target = None  # type: ignore[assignment]

    def is_target_exec_backend() -> bool:  # type: ignore[misc]
        return False

from .loader import GenericQADataLoader


# ── Scoring spec ──────────────────────────────────────────────────────────────

# Soft scores from all scorers are clamped to this range. ``custom_python`` MUST
# be clamped too (honest-mistake containment); see _score_custom_python.
_SCORE_MIN, _SCORE_MAX = 0.0, 1.0

_VALID_SCORERS = {"exact", "fuzzy", "f1", "llm_judge", "geval", "custom_python"}


def _clamp01(x: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(_SCORE_MIN, min(_SCORE_MAX, v))


def _coerce_gold(ground_truth: Any) -> list[str]:
    """Normalize a ground_truth value into a list of acceptable gold strings."""
    if ground_truth is None:
        return []
    if isinstance(ground_truth, list):
        return [str(g) for g in ground_truth]
    if isinstance(ground_truth, dict):
        # Accept {"answers": [...]} or {"answer": "..."} shapes.
        if isinstance(ground_truth.get("answers"), list):
            return [str(g) for g in ground_truth["answers"]]
        if "answer" in ground_truth:
            return [str(ground_truth["answer"])]
        return [json.dumps(ground_truth, sort_keys=True, ensure_ascii=False)]
    return [str(ground_truth)]


# ── Built-in scorers (self-contained fallback; SQuAD-style normalization) ──────

import string
from collections import Counter

_ARTICLES = re.compile(r"\b(a|an|the)\b")


def _normalize(s: str) -> str:
    s = str(s).lower()
    s = "".join(ch for ch in s if ch not in string.punctuation)
    s = _ARTICLES.sub(" ", s)
    return " ".join(s.split()).strip()


def _builtin_exact(pred: str, golds: list[str]) -> float:
    np = _normalize(pred)
    return 1.0 if any(_normalize(g) == np for g in golds) else 0.0


def _builtin_fuzzy(pred: str, golds: list[str]) -> float:
    """Substring containment either direction → 1.0, else 0.0 (normalized)."""
    np = _normalize(pred)
    for g in golds:
        ng = _normalize(g)
        if ng and (ng in np or np in ng):
            return 1.0
    return 0.0


def _builtin_f1(pred: str, golds: list[str]) -> float:
    pred_tokens = _normalize(pred).split()
    if not pred_tokens:
        return 1.0 if any(not _normalize(g).split() for g in golds) else 0.0
    best = 0.0
    for g in golds:
        gt = _normalize(g).split()
        if not gt:
            continue
        common = Counter(pred_tokens) & Counter(gt)
        n = sum(common.values())
        if n == 0:
            continue
        prec = n / len(pred_tokens)
        rec = n / len(gt)
        best = max(best, 2 * prec * rec / (prec + rec))
    return best


_BUILTIN_DISPATCH = {
    "exact": _builtin_exact,
    "fuzzy": _builtin_fuzzy,
    "f1": _builtin_f1,
}


def _resolve_backend_grader():
    """Return the backend grading module if importable, else None.

    The real grader implementations (llm_judge / geval / custom_python sandbox)
    are owned by the backend ``skillopt_studio.grading`` package, built by another
    agent. We import it lazily and defensively so the env still runs (with built-in
    scorers) when that module is absent from the subprocess runtime.
    """
    for modname in ("skillopt_studio.grading", "skillopt_studio.grading.api"):
        try:
            import importlib

            return importlib.import_module(modname)
        except Exception:  # noqa: BLE001
            continue
    return None


# ── Answer parsing ─────────────────────────────────────────────────────────────

_ANSWER_TAG = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)
_ANSWER_PREFIX = re.compile(r"(?im)^\s*answer\s*[:\-]\s*(.+)$")


def parse_answer(text: str, mode: str = "answer_tag") -> str:
    """Extract the answer span from a raw model response.

    Modes:
    - ``answer_tag`` (default): last ``<answer>...</answer>`` block; fallback to
      ``Answer:`` line; fallback to last non-empty line.
    - ``answer_prefix``: last ``Answer:`` line; fallback to last non-empty line.
    - ``json``: parse JSON and return the ``answer`` field (or whole compacted JSON).
    - ``raw``/``full``: the whole stripped response.
    - a regex string: first capture group of the (last) match.
    """
    text = text or ""
    mode = (mode or "answer_tag").strip()

    if mode in ("raw", "full"):
        return text.strip()

    if mode == "json":
        try:
            obj = json.loads(text.strip())
            if isinstance(obj, dict):
                return str(obj.get("answer", json.dumps(obj, ensure_ascii=False)))
            return str(obj)
        except Exception:  # noqa: BLE001
            pass  # fall through to generic extraction

    if mode == "answer_tag":
        m = _ANSWER_TAG.findall(text)
        if m:
            return m[-1].strip()

    if mode in ("answer_tag", "answer_prefix"):
        pm = _ANSWER_PREFIX.findall(text)
        if pm:
            return pm[-1].strip()

    if mode not in ("answer_tag", "answer_prefix", "json"):
        # Treat as a custom regex.
        try:
            matches = re.findall(mode, text, re.DOTALL)
            if matches:
                last = matches[-1]
                return (last[0] if isinstance(last, tuple) else last).strip()
        except re.error:
            pass

    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else text.strip()


# ── Adapter ─────────────────────────────────────────────────────────────────────

class GenericQAEnv(EnvAdapter):
    """Reusable single-turn QA adapter for optimizing arbitrary skills."""

    def __init__(
        self,
        # Dataset / split (flat keys, mirrors SearchQAAdapter signature).
        data_path: str = "",
        split_dir: str = "",
        split_mode: str = "ratio",
        split_ratio: str = "2:1:7",
        split_seed: int = 42,
        split_output_dir: str = "",
        seed: int = 42,
        limit: int = 0,
        # Rollout / model.
        max_turns: int = 1,
        exec_timeout: int = 120,
        workers: int = 16,
        max_completion_tokens: int = 4096,
        # Reflect (verified flat keys).
        analyst_workers: int = 16,
        failure_only: bool = False,
        minibatch_size: int = 8,
        edit_budget: int = 4,
        # Scoring spec — may arrive as a nested dict (``scoring``) or flat keys.
        scoring: dict | None = None,
        scoring_type: str = "",
        scoring_threshold: float = 0.5,
        answer_parse: str = "answer_tag",
        judge_model: str = "",
        rubric: str = "",
        geval_criteria: str = "",
        custom_python: str = "",
        **_ignored: Any,
    ) -> None:
        self.max_turns = max(1, int(max_turns))
        self.exec_timeout = int(exec_timeout)
        self.workers = int(workers)
        self.max_completion_tokens = int(max_completion_tokens)
        self.analyst_workers = int(analyst_workers)
        self.failure_only = bool(failure_only)
        self.minibatch_size = int(minibatch_size)
        self.edit_budget = int(edit_budget)

        spec = dict(scoring or {})
        self.scoring_type = (spec.get("type") or scoring_type or "f1").strip().lower()
        if self.scoring_type not in _VALID_SCORERS:
            raise ValueError(
                f"generic_qa scoring.type must be one of {sorted(_VALID_SCORERS)}, "
                f"got {self.scoring_type!r}"
            )
        self.scoring_threshold = _clamp01(spec.get("threshold", scoring_threshold))
        self.answer_parse = spec.get("answer_parse") or answer_parse or "answer_tag"
        self.judge_model = spec.get("judge_model") or judge_model or ""
        self.rubric = spec.get("rubric") or rubric or ""
        self.geval_criteria = spec.get("criteria") or geval_criteria or self.rubric
        # custom_python code is NEVER inlined in the YAML; configgen writes it to a
        # chmod-600 sidecar and records ``custom_code_path``. Load it from there
        # (falling back to an inline ``custom_python`` kwarg only for unit tests).
        self.custom_python = custom_python or ""
        ccp = spec.get("custom_code_path") or ""
        if ccp:
            try:
                with open(ccp, encoding="utf-8") as fh:
                    self.custom_python = fh.read()
            except OSError as exc:
                print(f"    [generic_qa] custom_code_path unreadable ({ccp}): {exc}", flush=True)

        self.dataloader = GenericQADataLoader(
            split_dir=split_dir,
            data_path=data_path,
            split_mode=split_mode,
            split_ratio=split_ratio,
            split_seed=split_seed,
            split_output_dir=split_output_dir,
            seed=seed,
            limit=limit,
        )
        self._grader_mod = None  # resolved lazily on first score

    # ── Lifecycle ──────────────────────────────────────────────────────────
    def setup(self, cfg: dict) -> None:
        super().setup(cfg)
        self.dataloader.setup(cfg)

    def get_dataloader(self):
        return self.dataloader

    def get_task_types(self) -> list[str]:
        return ["qa"]

    # ── Env construction (mirrors SearchQAAdapter: env_manager is a list[dict]) ─
    def build_env_from_batch(self, batch, **kwargs):
        return list(getattr(batch, "payload", None) or [])

    def build_train_env(self, batch_size: int, seed: int, **kwargs):
        batch = self.dataloader.build_train_batch(batch_size=batch_size, seed=seed, **kwargs)
        return self.build_env_from_batch(batch, **kwargs)

    def build_eval_env(self, env_num: int, split: str, seed: int, **kwargs):
        batch = self.dataloader.build_eval_batch(env_num=env_num, split=split, seed=seed, **kwargs)
        return self.build_env_from_batch(batch, **kwargs)

    # ── Judge model-call binding (for llm_judge / geval) ──────────────────────
    def _judge_model_call(self, prompt: str, model: str) -> str:
        """Bind a judge ``model_call`` to SkillOpt's model layer.

        The judge is a single-turn chat completion: the rubric/scoring prompt is
        sent as the user message with an empty system prompt. The injected judge
        model is independent of the target/optimizer; temperature pinning is the
        backend's responsibility (the prompt forces a single normalized number).
        """
        if chat_target is None:
            raise RuntimeError("judge model_call requires skillopt.model.chat_target")
        response, _usage = chat_target(  # type: ignore[misc]
            system="",
            user=prompt,
            max_completion_tokens=256,
            retries=3,
            stage="judge",
            timeout=self.exec_timeout,
        )
        return response

    # ── Scoring ──────────────────────────────────────────────────────────────
    def _score(self, item: dict, predicted: str, raw_response: str) -> float:
        """Return a clamped soft score in [0,1] for *predicted* vs item ground truth.

        Built-in verifiable scorers (exact/fuzzy/f1) run inline. For
        llm_judge/geval/custom_python we delegate to the backend ``grading.score``
        adapter. We DO NOT silently fall back to f1 when the selected grader is
        configured but errors — that would mask a misconfiguration and confuse the
        optimizer. The f1 fallback applies ONLY when the backend grading module is
        genuinely unimportable in this runtime.
        """
        golds = _coerce_gold(item.get("ground_truth"))
        stype = self.scoring_type

        # Built-in verifiable scorers — always available, no external deps.
        if stype in _BUILTIN_DISPATCH:
            return _clamp01(_BUILTIN_DISPATCH[stype](predicted, golds))

        # llm_judge / geval / custom_python → delegate to backend grading.
        if self._grader_mod is None:
            self._grader_mod = _resolve_backend_grader() or False
        mod = self._grader_mod
        if not mod:
            # Backend grading not importable at all → degrade to f1 (last resort).
            print(
                f"    [generic_qa] scoring.type={stype!r} unavailable in runtime "
                f"(backend grading not importable); falling back to built-in f1.",
                flush=True,
            )
            return _clamp01(_builtin_f1(predicted, golds))

        fn = getattr(mod, "score", None)
        if not callable(fn):
            print(
                f"    [generic_qa] backend grading has no score(); falling back to f1.",
                flush=True,
            )
            return _clamp01(_builtin_f1(predicted, golds))

        model_call = self._judge_model_call if stype in ("llm_judge", "geval") else None
        result = fn(
            scoring_type=stype,
            prediction=predicted,
            ground_truth=item.get("ground_truth"),
            item=item,
            judge_model=self.judge_model,
            rubric=self.rubric,
            criteria=self.geval_criteria,
            custom_code=self.custom_python,
            threshold=self.scoring_threshold,
            model_call=model_call,
        )
        if isinstance(result, dict):
            result = result.get("soft", result.get("score", 0.0))
        return _clamp01(result)

    # ── Rollout ────────────────────────────────────────────────────────────
    def rollout(self, env_manager, skill_content: str, out_dir: str, **kwargs) -> list[dict]:
        """Single-turn rollout: system=skill_content, user=item.input.

        Writes ``predictions/<id>/conversation.json`` (so the shared reflect engine
        can read trajectories) and appends rollout results to ``results.jsonl``.
        Resume-aware: skips ids already present in ``results.jsonl``.
        """
        items: list[dict] = list(env_manager or [])
        os.makedirs(out_dir, exist_ok=True)
        results_path = os.path.join(out_dir, "results.jsonl")

        done_ids: set[str] = set()
        existing: list[dict] = []
        if os.path.exists(results_path):
            with open(results_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        done_ids.add(str(rec.get("id")))
                        existing.append(rec)
                    except json.JSONDecodeError:
                        continue

        pending = [it for it in items if str(it.get("id")) not in done_ids]
        if not pending:
            return existing

        if chat_target is None:
            raise RuntimeError(
                "generic_qa rollout requires skillopt.model.chat_target; it is not "
                "importable. Ensure SkillOpt is installed in this runtime."
            )
        if is_target_exec_backend():
            # Exec backends (codex_exec/claude_code_exec) need workspace harnessing
            # that this generic adapter does not implement. Fail loud and early.
            raise NotImplementedError(
                "generic_qa supports chat target backends (openai_chat/claude_chat/"
                "qwen_chat/minimax_chat). Exec backends are not supported."
            )

        results = list(existing)
        with open(results_path, "a", encoding="utf-8") as outf:
            for item in pending:
                rec = self._rollout_one(item, skill_content, out_dir)
                results.append(rec)
                outf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                outf.flush()
                print(
                    f"    [rollout] id={rec['id']} hard={rec['hard']} "
                    f"soft={rec['soft']:.3f}",
                    flush=True,
                )
        return results

    def _rollout_one(self, item: dict, skill_content: str, out_dir: str) -> dict:
        item_id = str(item.get("id"))
        question = str(item.get("input", ""))
        pred_dir = os.path.join(out_dir, "predictions", item_id)
        os.makedirs(pred_dir, exist_ok=True)

        rec: dict[str, Any] = {
            "id": item_id,
            "task_description": question,
            "task_type": str(item.get("metadata", {}).get("task_type") or "qa"),
            "hard": 0,
            "soft": 0.0,
            "predicted_answer": "",
            "response": "",
            "gold_answer": _coerce_gold(item.get("ground_truth")),
            "fail_reason": "",
            "agent_ok": False,
            "n_turns": 0,
        }

        system = skill_content or ""
        user = question
        try:
            response, _usage = chat_target(  # type: ignore[misc]
                system=system,
                user=user,
                max_completion_tokens=self.max_completion_tokens,
                retries=5,
                stage="rollout",
                timeout=self.exec_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            rec["fail_reason"] = f"error: {type(exc).__name__}: {exc}"
            self._write_conversation(pred_dir, system, user, "", rec)
            return rec

        rec["response"] = response
        rec["agent_ok"] = True
        rec["n_turns"] = 1
        predicted = parse_answer(response, self.answer_parse)
        rec["predicted_answer"] = predicted

        soft = _clamp01(self._score(item, predicted, response))
        rec["soft"] = soft
        rec["hard"] = int(soft >= self.scoring_threshold)
        if not rec["hard"]:
            rec["fail_reason"] = (
                f"score {soft:.3f} < threshold {self.scoring_threshold:.3f}: "
                f"predicted {predicted!r} vs gold {rec['gold_answer']!r}"
            )

        self._write_conversation(pred_dir, system, user, response, rec)
        return rec

    @staticmethod
    def _write_conversation(pred_dir: str, system: str, user: str, response: str, rec: dict) -> None:
        """Persist target prompts + conversation.json with an [EVALUATION RESULT]
        system turn, matching what the shared reflect formatter expects to read."""
        try:
            with open(os.path.join(pred_dir, "target_system_prompt.txt"), "w", encoding="utf-8") as fh:
                fh.write(system)
            with open(os.path.join(pred_dir, "target_user_prompt.txt"), "w", encoding="utf-8") as fh:
                fh.write(user)
            conversation = [{"type": "message", "turn": 1, "content": response}]
            eval_detail = (
                "[EVALUATION RESULT]\n"
                f"Predicted answer: {rec.get('predicted_answer')!r}\n"
                f"Gold answers: {rec.get('gold_answer')!r}\n"
                f"hard: {rec.get('hard')}\n"
                f"soft: {rec.get('soft'):.4f}"
            )
            conversation.append({"role": "system", "content": eval_detail})
            with open(os.path.join(pred_dir, "conversation.json"), "w", encoding="utf-8") as fh:
                json.dump(conversation, fh, ensure_ascii=False, indent=2)
        except Exception as exc:  # noqa: BLE001
            print(f"    [generic_qa] failed to persist conversation for {pred_dir}: {exc}", flush=True)

    # ── Reflect (delegate to shared minibatch reflect — verified signature) ───
    def reflect(self, results: list[dict], skill_content: str, out_dir: str, **kwargs) -> list[dict | None]:
        if run_minibatch_reflect is None:
            raise RuntimeError(
                "generic_qa reflect requires skillopt.gradient.reflect.run_minibatch_reflect; "
                "it is not importable. Ensure SkillOpt is installed in this runtime."
            )
        prediction_dir = kwargs.get("prediction_dir", os.path.join(out_dir, "predictions"))
        patches_dir = kwargs.get("patches_dir", os.path.join(out_dir, "patches"))
        random_seed = kwargs.get("random_seed")
        step_buffer_context = kwargs.get("step_buffer_context", "")
        meta_skill_context = kwargs.get("meta_skill_context", "")
        update_mode = getattr(self, "_cfg", {}).get("skill_update_mode", "patch")

        return run_minibatch_reflect(
            results=results,
            skill_content=skill_content,
            prediction_dir=prediction_dir,
            patches_dir=patches_dir,
            workers=self.analyst_workers,
            failure_only=self.failure_only,
            minibatch_size=self.minibatch_size,
            edit_budget=self.edit_budget,
            random_seed=random_seed,
            error_system=self.get_error_minibatch_prompt(),
            success_system=self.get_success_minibatch_prompt(),
            step_buffer_context=step_buffer_context,
            meta_skill_context=meta_skill_context,
            update_mode=update_mode,
        )


__all__ = ["GenericQAEnv", "parse_answer"]
