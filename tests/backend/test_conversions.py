"""Tests for the Convert-to-LangGraph pipeline + artifact parser.

No real subprocess is spawned: ``pipeline._run_stage`` and ``ensure_available``
are monkeypatched, so these run fast and offline. Covers env billing-safety,
stage ordering/argv, the failure-abort path, cancellation, and the defensive
outputs parser.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillopt_studio.domain import DoneEvent, StageEvent, TrainRunStatus
from skillopt_studio.langgraph import outputs, pipeline


# ── env billing safety ───────────────────────────────────────────────────────
def test_build_env_scrubs_api_keys_for_claude_cli(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-other")
    env = pipeline.build_env("claude_cli")
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env


def test_build_env_keeps_api_keys_for_api_backend(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    env = pipeline.build_env("api")
    assert env["ANTHROPIC_API_KEY"] == "sk-secret"


# ── stage construction ───────────────────────────────────────────────────────
def test_build_stages_order_and_argv(tmp_path):
    skill_dir = tmp_path / "s2lg"
    py = skill_dir / ".venv" / "bin" / "python"
    target = tmp_path / "skills" / "hello-world"
    stages = pipeline.build_stages(
        skill_dir=skill_dir, py=py, target_skill_dir=target,
        skill="hello-world", model="sonnet", run_parity=False,
    )
    names = [n for n, _, _ in stages]
    assert names == ["extract", "validate", "gen_evals", "pytest", "package", "improve"]

    extract_argv = stages[0][1]
    assert extract_argv[0] == str(py)
    assert "scripts/extract_graphspec.py" in extract_argv
    assert str(target) in extract_argv
    assert "--skills-root" in extract_argv and str(target.parent) in extract_argv
    assert "--force" in extract_argv

    # pytest stage uses an underscored module name.
    pytest_argv = next(a for n, a, _ in stages if n == "pytest")
    assert "evals/test_hello_world.py" in pytest_argv


def test_build_stages_parity_only_when_requested(tmp_path):
    common = dict(skill_dir=tmp_path, py=tmp_path / "py", target_skill_dir=tmp_path / "t",
                  skill="x", model="sonnet")
    without = [n for n, _, _ in pipeline.build_stages(run_parity=False, **common)]
    withp = pipeline.build_stages(run_parity=True, **common)
    assert "parity" not in without
    parity = next((e for n, _, e in withp if n == "parity"), None)
    assert parity == {"RUN_LIVE_EVALS": "1"}


# ── run_conversion: happy path, ordering, terminal event ─────────────────────
def _patch_available(monkeypatch, tmp_path):
    py = tmp_path / ".venv" / "bin" / "python"
    monkeypatch.setattr(pipeline, "ensure_available", lambda: (tmp_path, py))


def test_run_conversion_runs_all_stages_in_order(monkeypatch, tmp_path):
    _patch_available(monkeypatch, tmp_path)
    ran: list[str] = []

    def fake_stage(*, name, index, total, argv, cwd, env, on_event, handle):
        ran.append(name)
        on_event(StageEvent(stage=name, index=index, total=total))
        return pipeline.StageResult(name=name, ok=True, exit_code=0)

    monkeypatch.setattr(pipeline, "_run_stage", fake_stage)

    events = []
    summary = pipeline.run_conversion(
        target_skill_dir=tmp_path / "skills" / "demo", skill_hint="demo",
        on_event=events.append,
    )
    assert ran == ["extract", "validate", "gen_evals", "pytest", "package", "improve"]
    assert summary["status"] == TrainRunStatus.completed.value
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].status == TrainRunStatus.completed


def test_run_conversion_aborts_after_failure(monkeypatch, tmp_path):
    _patch_available(monkeypatch, tmp_path)
    ran: list[str] = []

    def fake_stage(*, name, index, total, argv, cwd, env, on_event, handle):
        ran.append(name)
        # validate fails -> everything after is skipped.
        ok = name != "validate"
        return pipeline.StageResult(name=name, ok=ok, exit_code=0 if ok else 2)

    monkeypatch.setattr(pipeline, "_run_stage", fake_stage)

    events = []
    summary = pipeline.run_conversion(
        target_skill_dir=tmp_path / "skills" / "demo", skill_hint="demo",
        on_event=events.append,
    )
    assert ran == ["extract", "validate"]  # gen_evals onward skipped
    assert summary["status"] == TrainRunStatus.failed.value
    skipped = [s["name"] for s in summary["stages"] if s["skipped"]]
    assert skipped == ["gen_evals", "pytest", "package", "improve"]
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].status == TrainRunStatus.failed


def test_run_conversion_unavailable_emits_failed_done(monkeypatch, tmp_path):
    def boom():
        raise pipeline.LangGraphUnavailable("no repo")
    monkeypatch.setattr(pipeline, "ensure_available", boom)
    events = []
    summary = pipeline.run_conversion(
        target_skill_dir=tmp_path, skill_hint="demo", on_event=events.append,
    )
    assert summary["status"] == "failed"
    assert isinstance(events[-1], DoneEvent) and events[-1].status == TrainRunStatus.failed


# ── cancellation ─────────────────────────────────────────────────────────────
def test_handle_cancel_flag():
    h = pipeline.ConversionHandle()
    assert h.cancel() is False  # no live process
    assert h.cancelled is True


def test_run_conversion_skips_when_cancelled_first(monkeypatch, tmp_path):
    _patch_available(monkeypatch, tmp_path)

    def fake_stage(**kw):  # should never run
        raise AssertionError("stage ran despite pre-cancel")

    monkeypatch.setattr(pipeline, "_run_stage", fake_stage)

    def on_handle(h):
        h.cancel()  # cancel before any stage launches

    summary = pipeline.run_conversion(
        target_skill_dir=tmp_path, skill_hint="demo",
        on_event=lambda e: None, on_handle=on_handle,
    )
    assert summary["status"] == TrainRunStatus.cancelled.value


# ── outputs parser ───────────────────────────────────────────────────────────
def test_parse_conversion_degrades_when_nothing_exists(tmp_path):
    res = outputs.parse_conversion("ghost", skill_dir=tmp_path)
    assert res["spec"] is None
    assert res["validation"]["checks"] is None
    assert res["dist"] is None
    assert res["parity"] is None


def test_parse_conversion_reads_full_artifacts(tmp_path):
    (tmp_path / "training" / "specs").mkdir(parents=True)
    (tmp_path / "training" / "reports").mkdir(parents=True)
    dist = tmp_path / "dist" / "demo"
    dist.mkdir(parents=True)

    (tmp_path / "training" / "specs" / "demo.graphspec.json").write_text(json.dumps({
        "skill": "demo", "workflow_shape": "trivial",
        "nodes": [{"id": "a", "kind": "llm"},
                  {"id": "b", "kind": "subgraph", "skill": "child"}],
    }))
    (tmp_path / "training" / "reports" / "demo.json").write_text(json.dumps({
        "schema_ok": True, "codegen_ok": True, "compile_ok": True,
        "nodes_match": True, "edges_cover": True, "smoke_ok": True, "errors": [],
    }))
    (dist / "main.py").write_text("print('hi')")
    (dist / "requirements.txt").write_text("langgraph")
    (dist / "README.md").write_text("# demo\nrun it")

    res = outputs.parse_conversion("demo", skill_dir=tmp_path)
    assert res["spec"]["node_count"] == 2
    assert res["spec"]["children"] == ["child"]
    assert res["validation"]["all_green"] is True
    assert res["dist"]["has_main"] and res["dist"]["has_requirements"]
    assert "main.py" in res["dist"]["files"]
