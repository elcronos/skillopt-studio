"""Registration SHA-pin assertion test (#12)."""

from __future__ import annotations

import subprocess

import pytest

from skillopt_studio import config
from skillopt_studio.skillopt import registration


def _init_repo_at_sha(path, fake_sha_commit_msg="x"):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", fake_sha_commit_msg], check=True)


class TestAssertPinnedSha:
    def test_skips_when_not_git(self, tmp_path):
        # No .git → no-op, never raises.
        registration.assert_pinned_sha(tmp_path)

    def test_raises_on_mismatch(self, tmp_path):
        _init_repo_at_sha(tmp_path)
        # The repo's HEAD will not equal the pinned SHA → must raise.
        with pytest.raises(RuntimeError, match="SHA mismatch"):
            registration.assert_pinned_sha(tmp_path)

    def test_passes_when_match(self, tmp_path, monkeypatch):
        _init_repo_at_sha(tmp_path)
        head = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
        monkeypatch.setattr(config, "SKILLOPT_PINNED_SHA", head)
        registration.assert_pinned_sha(tmp_path)  # no raise

    def test_patch_aborts_on_drifted_checkout(self, tmp_path):
        # A scripts/ dir + drifted git HEAD → patch must refuse loudly.
        _init_repo_at_sha(tmp_path)
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "train.py").write_text(
            "def _register_builtins():\n    pass\n", encoding="utf-8"
        )
        with pytest.raises(RuntimeError, match="SHA mismatch"):
            registration.patch_register_builtins(tmp_path)
