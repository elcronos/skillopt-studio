"""Tests for per-role secret injection into the train subprocess env (#1).

Asserts a stored key reaches ``build_model_env`` under the correct (role-prefixed)
env var, and that secrets never appear in argv.
"""

from __future__ import annotations

from skillopt_studio.domain import ModelConfig
from skillopt_studio.skillopt import args as args_mod


class TestBuildModelEnvRoles:
    def test_shared_secret_azure(self):
        m = ModelConfig(backend="openai_chat")
        env = args_mod.build_model_env(m, secret="SHARED")
        assert env["AZURE_OPENAI_API_KEY"] == "SHARED"
        assert env["PYTHONUNBUFFERED"] == "1"

    def test_per_role_secrets_azure(self):
        m = ModelConfig(backend="openai_chat")
        env = args_mod.build_model_env(
            m, optimizer_secret="OPT", target_secret="TGT"
        )
        assert env["OPTIMIZER_AZURE_OPENAI_API_KEY"] == "OPT"
        assert env["TARGET_AZURE_OPENAI_API_KEY"] == "TGT"

    def test_per_role_different_backends(self):
        m = ModelConfig(
            backend="openai_chat",
            optimizer_backend="openai_chat",
            target_backend="minimax_chat",
        )
        env = args_mod.build_model_env(
            m, optimizer_secret="OPT", target_secret="TGT"
        )
        assert env["OPTIMIZER_AZURE_OPENAI_API_KEY"] == "OPT"
        assert env["TARGET_MINIMAX_API_KEY"] == "TGT"

    def test_claude_uses_anthropic_key(self):
        m = ModelConfig(backend="claude_chat")
        env = args_mod.build_model_env(m, secret="SK-ANT")
        assert env["ANTHROPIC_API_KEY"] == "SK-ANT"

    def test_redaction_masks_role_keys(self):
        m = ModelConfig(backend="openai_chat")
        env = args_mod.build_model_env(m, optimizer_secret="OPT", target_secret="TGT")
        red = args_mod.redact_env(env)
        assert red["OPTIMIZER_AZURE_OPENAI_API_KEY"] == "***REDACTED***"
        assert red["TARGET_AZURE_OPENAI_API_KEY"] == "***REDACTED***"


class TestStoredKeyReachesEnv:
    def test_stored_key_flows_to_build_model_env(self, monkeypatch, tmp_path):
        """A key stored via keys.store reaches build_model_env (the runs.py path).

        Uses the file fallback by forcing keyring unavailable, with the fallback
        path redirected into a tmp dir so no real keychain/file is touched.
        """
        from skillopt_studio.keys import store as keystore

        monkeypatch.setattr(keystore, "_keyring", lambda: None)
        monkeypatch.setattr(keystore, "_FALLBACK_PATH", tmp_path / ".keys.json")

        keystore.set_key("openai_chat", "optimizer", "OPT-SECRET")
        keystore.set_key("openai_chat", "target", "TGT-SECRET")

        # Mirror runs.py._resolve_role_secrets resolution.
        opt = keystore.get_key("openai_chat", "optimizer")
        tgt = keystore.get_key("openai_chat", "target")
        assert opt == "OPT-SECRET"
        assert tgt == "TGT-SECRET"

        m = ModelConfig(backend="openai_chat")
        env = args_mod.build_model_env(m, optimizer_secret=opt, target_secret=tgt)
        assert env["OPTIMIZER_AZURE_OPENAI_API_KEY"] == "OPT-SECRET"
        assert env["TARGET_AZURE_OPENAI_API_KEY"] == "TGT-SECRET"


class TestArgvHasNoSecret:
    def test_train_argv_no_secret(self, tmp_path):
        argv = args_mod.build_train_argv(
            config_path=tmp_path / "c.yaml",
            skillopt_clone_dir=tmp_path,
        )
        joined = " ".join(argv)
        for needle in ("API_KEY", "SECRET", "OPT-SECRET"):
            assert needle not in joined
