"""configgen tests (#9, #11).

- The generated YAML must survive SkillOpt's real load_config + flatten_config
  deep-merge IF skillopt is importable; otherwise we assert the config is shaped
  so a deep-merge preserves base sub-keys (partial sections only) and never sets
  evaluation.use_gate=false.
- custom_python code is NEVER persisted in the YAML — only a chmod-600 sidecar
  path is recorded (#11).
"""

from __future__ import annotations

import importlib.util
import os
import stat

import pytest
import yaml

from skillopt_studio.skillopt import configgen

_SKILLOPT = importlib.util.find_spec("skillopt") is not None


def _gen(tmp_path, scoring, **kw):
    skill = tmp_path / "skill.md"
    skill.write_text("# seed skill\n", encoding="utf-8")
    data = tmp_path / "dataset.json"
    data.write_text("[]", encoding="utf-8")
    return configgen.generate(
        slug="run-x",
        skill_init_path=str(skill),
        data_path=str(data),
        out_root=str(tmp_path / "out"),
        scoring=scoring,
        configs_dir=str(tmp_path / "configs"),
        **kw,
    )


class TestPartialSectionsPreserveBase:
    def test_only_customized_keys_emitted(self, tmp_path):
        path = _gen(
            tmp_path,
            {"type": "f1", "threshold": 0.5},
            optimizer={"learning_rate": 7},  # only one optimizer key
            gradient={"analyst_workers": 32},
            train={"num_epochs": 2},
        )
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert cfg["_base_"]
        # Partial optimizer section: only learning_rate, so base lr_scheduler etc.
        # survive the deep-merge against _base_.
        assert cfg["optimizer"] == {"learning_rate": 7}
        assert cfg["gradient"] == {"analyst_workers": 32}
        assert cfg["train"] == {"num_epochs": 2}
        assert cfg["env"]["name"] == "generic_qa"

    def test_never_sets_use_gate_false(self, tmp_path):
        path = _gen(
            tmp_path,
            {"type": "f1"},
            evaluation={"use_gate": False, "eval_test": True},
        )
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        # use_gate=false is stripped (base stays true); other keys survive.
        assert "use_gate" not in cfg.get("evaluation", {})
        assert cfg["evaluation"]["eval_test"] is True

    def test_deep_merge_preserves_base_subkeys_simulation(self, tmp_path):
        # Simulate SkillOpt's deep-merge: base optimizer has many keys; the
        # generated partial must NOT wipe them.
        base = {
            "optimizer": {"learning_rate": 4, "lr_scheduler": "cosine",
                          "skill_update_mode": "patch"},
            "evaluation": {"use_gate": True, "eval_test": True},
        }
        path = _gen(tmp_path, {"type": "f1"}, optimizer={"learning_rate": 9})
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))

        def deep_merge(b, o):
            out = dict(b)
            for k, v in o.items():
                if isinstance(v, dict) and isinstance(out.get(k), dict):
                    out[k] = deep_merge(out[k], v)
                else:
                    out[k] = v
            return out

        merged = deep_merge(base, {k: v for k, v in cfg.items() if k != "_base_"})
        assert merged["optimizer"]["learning_rate"] == 9
        assert merged["optimizer"]["lr_scheduler"] == "cosine"  # preserved
        assert merged["optimizer"]["skill_update_mode"] == "patch"  # preserved
        assert merged["evaluation"]["use_gate"] is True  # never dropped


class TestCustomCodeNotPersisted:
    def test_custom_code_goes_to_sidecar_not_yaml(self, tmp_path):
        code = "def score(prediction, ground_truth, item=None):\n    return 1.0\n"
        path = _gen(
            tmp_path,
            {"type": "custom_python", "threshold": 0.5},
            custom_code=code,
        )
        raw = path.read_text(encoding="utf-8")
        assert "def score" not in raw  # code NEVER inlined
        cfg = yaml.safe_load(raw)
        scoring = cfg["env"]["scoring"]
        assert "custom_code" not in scoring
        ccp = scoring["custom_code_path"]
        assert os.path.isfile(ccp)
        # sidecar is chmod 600
        mode = stat.S_IMODE(os.stat(ccp).st_mode)
        assert mode == 0o600
        assert "def score" in open(ccp, encoding="utf-8").read()


@pytest.mark.skipif(not _SKILLOPT, reason="skillopt not installed")
class TestRealLoadConfig:
    def test_generated_survives_load_and_flatten(self, tmp_path):
        from skillopt.config import flatten_config, load_config  # type: ignore

        path = _gen(tmp_path, {"type": "f1"}, optimizer={"learning_rate": 5})
        cfg = load_config(str(path), [])
        flat = flatten_config(cfg)
        assert flat is not None
        # edit_budget derives from optimizer.learning_rate; lr_scheduler from base.
        assert flat.get("edit_budget") == 5
