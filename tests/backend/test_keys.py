"""Tests for the keys subsystem: store roundtrip + env scrub correctness."""

from __future__ import annotations

import json
import os
import stat

import pytest

from skillopt_studio.keys import scrub_env, is_secret_var


# ---------------------------------------------------------------------------
# scrub
# ---------------------------------------------------------------------------
class TestScrub:
    def test_removes_known_vars(self):
        env = {
            "ANTHROPIC_API_KEY": "x",
            "AZURE_OPENAI_API_KEY": "x",
            "AZURE_OPENAI_ENDPOINT": "x",
            "OPENAI_API_KEY": "x",
            "QWEN_API_KEY": "x",
            "MINIMAX_API_KEY": "x",
            "PATH": "/usr/bin",
            "HOME": "/home/u",
        }
        scrubbed = scrub_env(env)
        assert "PATH" in scrubbed
        assert "HOME" in scrubbed
        for secret in (
            "ANTHROPIC_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
            "OPENAI_API_KEY",
            "QWEN_API_KEY",
            "MINIMAX_API_KEY",
        ):
            assert secret not in scrubbed

    def test_removes_role_prefixed_overrides(self):
        env = {
            "OPTIMIZER_AZURE_OPENAI_API_KEY": "x",
            "TARGET_AZURE_OPENAI_ENDPOINT": "x",
            "SAFE_VAR": "ok",
        }
        scrubbed = scrub_env(env)
        assert scrubbed == {"SAFE_VAR": "ok"}

    def test_heuristic_catches_unknown_secrets(self):
        assert is_secret_var("SOME_SERVICE_TOKEN")
        assert is_secret_var("MY_SECRET")
        assert is_secret_var("DB_PASSWORD")
        assert not is_secret_var("PATH")
        assert not is_secret_var("LANG")

    def test_does_not_mutate_input(self):
        env = {"ANTHROPIC_API_KEY": "x", "PATH": "/bin"}
        scrub_env(env)
        assert "ANTHROPIC_API_KEY" in env  # original untouched


# ---------------------------------------------------------------------------
# store roundtrip (file fallback forced for determinism)
# ---------------------------------------------------------------------------
class TestStore:
    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        import skillopt_studio.keys.store as store_mod

        # Force the file-fallback path so the test never touches the real keyring.
        monkeypatch.setattr(store_mod, "_keyring", lambda: None)
        monkeypatch.setattr(store_mod, "_FALLBACK_PATH", tmp_path / ".keys.json")
        return store_mod

    def test_set_get_roundtrip(self, store):
        mech = store.set_key("openai_chat", "optimizer", "sk-abc123")
        assert mech == "file"
        assert store.get_key("openai_chat", "optimizer") == "sk-abc123"

    def test_has_key(self, store):
        assert not store.has_key("claude_chat", "target")
        store.set_key("claude_chat", "target", "v")
        assert store.has_key("claude_chat", "target")

    def test_delete(self, store):
        store.set_key("qwen_chat", "optimizer", "v")
        assert store.delete_key("qwen_chat", "optimizer") is True
        assert store.get_key("qwen_chat", "optimizer") is None
        assert store.delete_key("qwen_chat", "optimizer") is False

    def test_list_keys(self, store):
        store.set_key("openai_chat", "optimizer", "a")
        store.set_key("openai_chat", "target", "b")
        assert store.list_keys() == ["openai_chat/optimizer", "openai_chat/target"]

    def test_fallback_file_is_chmod_600(self, store):
        store.set_key("openai_chat", "optimizer", "secret")
        mode = stat.S_IMODE(os.stat(store._FALLBACK_PATH).st_mode)
        assert mode == 0o600

    def test_value_persisted_but_not_in_listing(self, store):
        store.set_key("openai_chat", "optimizer", "sk-secret")
        # value present in file (it's the storage), but list_keys never returns it
        raw = json.loads(store._FALLBACK_PATH.read_text())
        assert raw["openai_chat/optimizer"] == "sk-secret"
        assert all("sk-secret" not in entry for entry in store.list_keys())
