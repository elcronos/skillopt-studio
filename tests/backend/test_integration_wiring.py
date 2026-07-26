"""HIGH integration wiring test (validators' recommendation).

Drives ``POST /api/runs/train`` with the FRONTEND payload shape through the real
FastAPI app + TestClient, with the runner subprocess stubbed. Asserts:
- the app boots and all routers mount (200 on /);
- the generated config exists and is generic_qa-shaped;
- the per-role secret stored in the keyring reaches the subprocess env that the
  (stubbed) runner receives — NEVER in argv;
- the grader dispatch is non-f1 (the generated scoring block selects geval);
- GET /runs/{id}, /versions, /scores return the documented shapes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from skillopt_studio.api import runs as runs_mod
from skillopt_studio.domain import Skill, ProviderName, TrainRunStatus
from skillopt_studio.keys import store as keystore
from skillopt_studio.main import create_app
from skillopt_studio.skillopt import runner as runner_mod


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # Redirect the key fallback into tmp + force keyring off (deterministic).
    monkeypatch.setattr(keystore, "_keyring", lambda: None)
    monkeypatch.setattr(keystore, "_FALLBACK_PATH", tmp_path / ".keys.json")

    app = create_app()
    with TestClient(app) as c:
        yield c


def _write_fake_run_tree(out_root: str) -> None:
    """Write a minimal SkillOpt-shaped run tree so parse_run_tree succeeds."""
    root = Path(out_root)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    (root / "config.yaml").write_text("env:\n  name: generic_qa\n", encoding="utf-8")
    (root / "best_skill.md").write_text("# optimized skill\n", encoding="utf-8")
    (root / "skills" / "skill_v0001.md").write_text("# v1\n", encoding="utf-8")
    with (root / "results.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "1", "step": 1, "hard": 1, "soft": 0.9}) + "\n")
    # a selection score line
    with (root / "gate.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"phase": "selection", "step": 1, "score": 0.8}) + "\n")


def test_boot_all_routers_mount(client):
    r = client.get("/")
    assert r.status_code == 200
    mounted = r.json()["mounted_routers"]
    for name in ("health", "skills", "datasets", "graders", "models", "runs", "stream"):
        assert name in mounted


def test_frontend_train_payload_wires_everything(client, monkeypatch, tmp_path):
    captured: dict = {}

    # Stub the scanner so skill_id resolves to a known skill body.
    fake_skill = Skill(
        id="claude:demo",
        name="demo",
        provider=ProviderName.claude,
        source_path=str(tmp_path / "src_skill.md"),
        body="# demo seed skill body\n",
    )
    monkeypatch.setattr(runs_mod, "importlib", runs_mod.importlib)  # keep ref

    import skillopt_studio.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "scan_all", lambda cwd: [fake_skill])

    # Store per-role keys; these must reach the subprocess env.
    keystore.set_key("openai_chat", "optimizer", "OPT-KEY")
    keystore.set_key("openai_chat", "target", "TGT-KEY")

    # Materialize a dataset via the real store API.
    r = client.post("/api/datasets", json={
        "name": "wiretest",
        "split_mode": "ratio",
        "split_ratio": "2:1:7",
        "cases": [
            {"id": "1", "input": "what is the capital of France?",
             "ground_truth": "a long descriptive free-text answer about Paris being the capital and largest city of France"},
        ],
    })
    assert r.status_code in (200, 201), r.text

    # Stub the runner: capture env + argv, write a fake run tree, mark completed.
    def fake_run_train(*, argv, env, on_event, cwd=None, on_handle=None, run_id=""):
        captured["argv"] = list(argv)
        captured["env"] = dict(env)
        # find the out_root from the generated config path in argv
        cfg_path = argv[argv.index("--config") + 1]
        cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
        captured["config"] = cfg
        _write_fake_run_tree(cfg["env"]["out_root"])
        return TrainRunStatus.completed

    monkeypatch.setattr(runner_mod, "run_train", fake_run_train)

    # FRONTEND-shaped payload.
    payload = {
        "slug": "wire",
        "skill_id": "claude:demo",
        "dataset_name": "wiretest",
        "model_config": {"backend": "openai_chat", "optimizer_model": "gpt-5.5",
                         "target_model": "gpt-5.5"},
        "grader": {"type": "geval", "threshold": 0.5,
                   "criteria": "Is the answer faithful and complete?"},
        "train": {"num_epochs": 2, "batch_size": 8, "learning_rate": 6,
                  "lr_scheduler": "linear", "analyst_workers": 4, "seed": 7},
    }
    r = client.post("/api/runs/train", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    run_id = body["id"]
    assert body["launched"] is True
    assert body["status"] in ("running", "completed")
    cfg_path = body["config_path"]
    assert Path(cfg_path).is_file()

    # ── Config generated correctly ──
    cfg = captured["config"]
    assert cfg["env"]["name"] == "generic_qa"
    assert cfg["env"]["scoring"]["type"] == "geval"  # grader dispatch not-f1
    assert cfg["optimizer"]["learning_rate"] == 6
    assert cfg["optimizer"]["lr_scheduler"] == "linear"
    assert cfg["gradient"]["analyst_workers"] == 4
    assert cfg["train"]["num_epochs"] == 2

    # ── Secret resolved into the subprocess env (never argv) ──
    env = captured["env"]
    assert env["OPTIMIZER_AZURE_OPENAI_API_KEY"] == "OPT-KEY"
    assert env["TARGET_AZURE_OPENAI_API_KEY"] == "TGT-KEY"
    joined_argv = " ".join(captured["argv"])
    assert "OPT-KEY" not in joined_argv and "TGT-KEY" not in joined_argv

    # Wait for the background runner thread to finish writing the fake tree.
    import time
    for _ in range(100):
        if client.get(f"/api/runs/{run_id}").json()["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.02)

    # ── GET /runs/{id} shape ──
    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["id"] == run_id
    assert "outputs" in detail or "partial" in detail

    # ── GET /runs/{id}/versions shape ──
    r = client.get(f"/api/runs/{run_id}/versions")
    assert r.status_code == 200
    versions = r.json()["versions"]
    assert isinstance(versions, list)
    assert any(v.get("is_best") for v in versions)
    assert all({"step", "md_text", "is_best"} <= set(v) for v in versions)

    # ── GET /runs/{id}/scores shape ──
    r = client.get(f"/api/runs/{run_id}/scores")
    assert r.status_code == 200
    scores = r.json()["scores"]
    assert isinstance(scores, list)
    for p in scores:
        assert {"step", "epoch", "train_score", "sel_score", "accepted"} <= set(p)


def test_eval_accepts_body_split(client, monkeypatch, tmp_path):
    # Create a run with a best skill present, then drive eval with a JSON body.
    import skillopt_studio.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "scan_all", lambda cwd: [
        Skill(id="claude:demo", name="demo", provider=ProviderName.claude,
              source_path=str(tmp_path / "s.md"), body="# seed\n"),
    ])
    client.post("/api/datasets", json={
        "name": "evalds", "split_mode": "ratio", "split_ratio": "2:1:7",
        "cases": [{"id": "1", "input": "q", "ground_truth": "a"}],
    })

    captured = {}

    def fake_run_train(*, argv, env, on_event, cwd=None, on_handle=None, run_id=""):
        cfg_path = argv[argv.index("--config") + 1]
        cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
        _write_fake_run_tree(cfg["env"]["out_root"])
        captured.setdefault("splits", [])
        # second invocation is eval; record --split
        if "--split" in argv:
            captured["splits"].append(argv[argv.index("--split") + 1])
        return TrainRunStatus.completed

    monkeypatch.setattr(runner_mod, "run_train", fake_run_train)

    r = client.post("/api/runs/train", json={
        "slug": "ev", "skill_id": "claude:demo", "dataset_name": "evalds",
        "grader": {"type": "f1"},
    })
    run_id = r.json()["id"]

    # Wait for the background runner thread to finish writing the fake tree.
    import time
    for _ in range(100):
        if client.get(f"/api/runs/{run_id}").json()["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.02)

    # eval with split in the JSON BODY (not query param).
    r = client.post(f"/api/runs/{run_id}/eval", json={"split": "valid"})
    assert r.status_code == 200, r.text
    assert r.json()["split"] == "valid"
    eval_id = r.json()["id"]
    for _ in range(100):
        if client.get(f"/api/runs/{eval_id}").json()["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.02)
    assert "valid" in captured.get("splits", [])
