"""Dataloader for the generic_qa environment.

``GenericQADataLoader`` is a thin subclass of SkillOpt's
:class:`skillopt.datasets.base.SplitDataLoader`. It reads a SELF-CONTAINED
dataset file (``dataset.json`` by default) which is a JSON array of items::

    [{"id": "...", "input": "...", "ground_truth": "...", "metadata": {...}}, ...]

Unlike searchqa (which uses ``split_mode=split_dir`` with an external corpus),
generic_qa carries everything inline so any skill can be optimized with a single
uploaded file. Both split modes from SkillOpt are supported:

- ``split_mode="ratio"`` — deterministic train/val/test split derived from the
  data via ``split_ratio`` (a ``"train:val:test"`` colon string, e.g. ``"2:1:7"``).
- ``split_mode="split_dir"`` — pre-split ``train/``/``val/``/``test/`` directories,
  each containing a JSON array (the base class default loader handles this).

Design notes / assumptions (verified against SkillOpt source at pinned SHA):
- ``SplitDataLoader.__init__`` accepts ``(split_dir, data_path, split_mode,
  split_ratio, split_seed, split_output_dir, seed, limit)``; ``setup(cfg)`` fills
  any blanks from the flattened config and materializes the ratio split. We only
  override raw-item loading so the inline ``{id,input,ground_truth,metadata}``
  schema is accepted as-is. The base class' ``load_split_items`` already reads a
  JSON array per split dir, which matches what ``write_split_items`` produces.
- We do NOT rename fields here: SkillOpt items remain plain dicts. The env
  (``env.py``) is responsible for mapping ``input``→prompt and
  ``ground_truth``→scoring reference at rollout time.
"""
from __future__ import annotations

import json
import os

try:  # Real dependency when running inside the SkillOpt venv.
    from skillopt.datasets.base import SplitDataLoader

    _HAVE_SKILLOPT = True
except Exception:  # pragma: no cover - allows py_compile / unit import without skillopt
    _HAVE_SKILLOPT = False

    class SplitDataLoader:  # type: ignore[no-redef]
        """Minimal stand-in so the loader imports/instantiates without skillopt.

        Mirrors only the constructor surface SkillOpt's real ``SplitDataLoader``
        exposes; ``setup``/batch methods are no-ops here and are NEVER used in the
        real runtime (where the genuine base class is imported above).
        """

        def __init__(
            self,
            split_dir: str = "",
            data_path: str = "",
            split_mode: str = "ratio",
            split_ratio: str = "2:1:7",
            split_seed: int = 42,
            split_output_dir: str = "",
            seed: int = 42,
            limit: int = 0,
            **kwargs: object,
        ) -> None:
            self.split_dir = split_dir
            self.data_path = data_path
            self.split_mode = split_mode
            self.split_ratio = split_ratio
            self.split_seed = int(split_seed)
            self.split_output_dir = split_output_dir
            self.seed = seed
            self.limit = limit
            self._splits: dict[str, list[dict]] = {}

        def setup(self, cfg: dict) -> None:  # pragma: no cover - stub only
            raise RuntimeError("GenericQADataLoader.setup requires skillopt to be installed")


DEFAULT_DATASET_FILENAME = "dataset.json"


def _load_json_array(path: str) -> list[dict]:
    """Load a JSON array (or ``{"data": [...]}``) of item dicts from *path*."""
    with open(path, encoding="utf-8") as fh:
        content = fh.read().strip()
    if not content:
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # JSONL fallback.
        items: list[dict] = []
        for line in content.splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
        return items
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list):
            return nested
        return list(data.values())
    raise ValueError(f"generic_qa dataset must be a JSON array or {{'data': [...]}}, got {type(data).__name__}")


def normalize_item(item: dict, index: int) -> dict:
    """Return a copy of *item* with the canonical generic_qa fields present.

    Guarantees ``id`` (string), ``input`` (string), ``ground_truth`` (string),
    and ``metadata`` (dict). Unknown keys are preserved untouched.
    """
    if not isinstance(item, dict):
        raise ValueError(f"generic_qa item #{index} is not an object: {item!r}")
    out = dict(item)
    out["id"] = str(out.get("id", index))
    out["input"] = str(out.get("input", "") or "")
    gt = out.get("ground_truth", "")
    out["ground_truth"] = "" if gt is None else (gt if isinstance(gt, (list, dict)) else str(gt))
    md = out.get("metadata")
    out["metadata"] = md if isinstance(md, dict) else {}
    return out


class GenericQADataLoader(SplitDataLoader):  # type: ignore[misc]
    """Self-contained dataset loader for arbitrary single-turn QA-style skills."""

    def load_raw_items(self, data_path: str) -> list[dict]:
        """Load + normalize raw items for the ratio-split path.

        Accepts either a single JSON/JSONL file or a directory containing exactly
        one ``dataset.json``/``*.json``/``*.jsonl`` file.
        """
        resolved = data_path
        if os.path.isdir(data_path):
            candidate = os.path.join(data_path, DEFAULT_DATASET_FILENAME)
            if os.path.isfile(candidate):
                resolved = candidate
            else:
                jsons = sorted(
                    p for p in os.listdir(data_path)
                    if p.endswith((".json", ".jsonl"))
                )
                if len(jsons) != 1:
                    raise ValueError(
                        "generic_qa data_path directory must contain exactly one "
                        f"JSON/JSONL file (or a {DEFAULT_DATASET_FILENAME}); got: {jsons}"
                    )
                resolved = os.path.join(data_path, jsons[0])
        raw = _load_json_array(resolved)
        return [normalize_item(it, i) for i, it in enumerate(raw)]

    def load_split_items(self, split_path: str) -> list[dict]:
        """Load + normalize items for one pre-split directory (split_dir mode)."""
        import glob

        json_files = sorted(glob.glob(os.path.join(split_path, "*.json")))
        json_files += sorted(glob.glob(os.path.join(split_path, "*.jsonl")))
        if not json_files:
            raise FileNotFoundError(f"No .json/.jsonl file found in {split_path}")
        raw = _load_json_array(json_files[0])
        if not isinstance(raw, list):
            raise ValueError(f"Expected a JSON array in {json_files[0]}")
        return [normalize_item(it, i) for i, it in enumerate(raw)]


__all__ = ["GenericQADataLoader", "normalize_item", "DEFAULT_DATASET_FILENAME"]
