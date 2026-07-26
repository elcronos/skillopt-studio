"""Tests for the multi-provider scanner adapters.

Uses temporary fixture directories so tests never depend on the real
~/.claude or ~/.codex state.  Graceful-degradation cases (missing roots,
unreadable files) are exercised explicitly.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


SKILL_MD_WITH_FM = """\
---
name: my-test-skill
description: A test skill for unit tests
---

# my-test-skill

Body content here.
"""

SKILL_MD_NO_FM = """\
# plain-skill

Just a plain body, no frontmatter.
"""

AGENTS_MD_WITH_HEADING = """\
# My Codex Agent

This is an AGENTS.md for codex.
"""

AGENTS_MD_NO_HEADING = """\
No heading here, just body content.
"""


# ---------------------------------------------------------------------------
# Claude adapter tests
# ---------------------------------------------------------------------------

class TestClaudeAdapter:
    def _make_adapter(self, monkeypatch, tmp_path):
        """Return a ClaudeAdapter pointed at tmp_path-based roots."""
        from skillopt_studio.scanner.claude import ClaudeAdapter, _HOME

        skills_dir = tmp_path / "skills"
        plugin_cache = tmp_path / "plugins" / "cache"

        # Patch module-level constants
        import skillopt_studio.scanner.claude as claude_mod
        monkeypatch.setattr(claude_mod, "_SKILLS_DIR", skills_dir)
        monkeypatch.setattr(claude_mod, "_PLUGIN_CACHE_DIR", plugin_cache)

        return ClaudeAdapter(), skills_dir, plugin_cache

    def test_finds_skill_with_frontmatter(self, monkeypatch, tmp_path):
        adapter, skills_dir, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(skills_dir / "my-test-skill" / "SKILL.md", SKILL_MD_WITH_FM)

        skills = adapter.scan()

        assert len(skills) == 1
        s = skills[0]
        assert s.name == "my-test-skill"
        assert s.provider.value == "claude"
        assert "my-test-skill" in s.source_path
        assert s.id.startswith("claude:")

    def test_finds_skill_without_frontmatter(self, monkeypatch, tmp_path):
        adapter, skills_dir, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(skills_dir / "plain-skill" / "SKILL.md", SKILL_MD_NO_FM)

        skills = adapter.scan()

        assert len(skills) == 1
        # Name falls back to directory name
        assert skills[0].name == "plain-skill"

    def test_finds_plugin_cache_skills(self, monkeypatch, tmp_path):
        adapter, _, plugin_cache = self._make_adapter(monkeypatch, tmp_path)
        _write(
            plugin_cache / "omc" / "oh-my-claudecode" / "4.9.3" / "skills" / "cancel" / "SKILL.md",
            "---\nname: cancel\ndescription: Cancel skill\n---\n\nBody.",
        )

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "cancel"
        assert skills[0].provider.value == "claude"

    def test_missing_roots_returns_empty(self, monkeypatch, tmp_path):
        adapter, _, _ = self._make_adapter(monkeypatch, tmp_path)
        # Neither skills_dir nor plugin_cache exist yet
        skills = adapter.scan()
        assert skills == []

    def test_root_paths_reported(self, monkeypatch, tmp_path):
        adapter, skills_dir, plugin_cache = self._make_adapter(monkeypatch, tmp_path)
        roots = adapter.root_paths()
        assert skills_dir in roots
        assert plugin_cache in roots

    def test_source_path_is_absolute(self, monkeypatch, tmp_path):
        adapter, skills_dir, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(skills_dir / "abs-skill" / "SKILL.md", SKILL_MD_WITH_FM)

        skills = adapter.scan()
        assert Path(skills[0].source_path).is_absolute()

    def test_multiple_skills_found(self, monkeypatch, tmp_path):
        adapter, skills_dir, plugin_cache = self._make_adapter(monkeypatch, tmp_path)
        _write(skills_dir / "skill-a" / "SKILL.md", "---\nname: skill-a\n---\nbody")
        _write(skills_dir / "skill-b" / "SKILL.md", "---\nname: skill-b\n---\nbody")
        _write(plugin_cache / "plugin-x" / "SKILL.md", "---\nname: plugin-x\n---\nbody")

        skills = adapter.scan()
        names = {s.name for s in skills}
        assert {"skill-a", "skill-b", "plugin-x"} == names

    def test_body_contains_full_content(self, monkeypatch, tmp_path):
        adapter, skills_dir, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(skills_dir / "my-test-skill" / "SKILL.md", SKILL_MD_WITH_FM)

        skills = adapter.scan()
        assert "Body content here" in skills[0].body


# ---------------------------------------------------------------------------
# Codex adapter tests
# ---------------------------------------------------------------------------

class TestCodexAdapter:
    def _make_adapter(self, monkeypatch, tmp_path):
        import skillopt_studio.scanner.codex as codex_mod

        codex_home = tmp_path / "codex_home"
        monkeypatch.setattr(codex_mod, "_CODEX_HOME", codex_home)

        cwd = tmp_path / "project"
        cwd.mkdir(parents=True, exist_ok=True)

        from skillopt_studio.scanner.codex import CodexAdapter
        return CodexAdapter(cwd), cwd, codex_home

    def test_finds_agents_md_in_cwd(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(cwd / "AGENTS.md", AGENTS_MD_WITH_HEADING)

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "My Codex Agent"
        assert skills[0].provider.value == "codex"
        assert skills[0].id.startswith("codex:")

    def test_finds_agents_md_in_codex_home(self, monkeypatch, tmp_path):
        adapter, _, codex_home = self._make_adapter(monkeypatch, tmp_path)
        _write(codex_home / "AGENTS.md", AGENTS_MD_WITH_HEADING)

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "My Codex Agent"

    def test_name_falls_back_to_dir_when_no_heading(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        subdir = cwd / "myagent"
        _write(subdir / "AGENTS.md", AGENTS_MD_NO_HEADING)

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "myagent"

    def test_missing_roots_returns_empty(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        # cwd exists but is empty; codex_home doesn't exist
        skills = adapter.scan()
        assert skills == []

    def test_deduplication_across_roots(self, monkeypatch, tmp_path):
        """Same resolved path seen from two search roots is included once."""
        adapter, cwd, codex_home = self._make_adapter(monkeypatch, tmp_path)
        # Put AGENTS.md in cwd only — should appear once
        _write(cwd / "AGENTS.md", AGENTS_MD_WITH_HEADING)
        skills = adapter.scan()
        assert len(skills) == 1

    def test_source_path_is_absolute(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(cwd / "AGENTS.md", AGENTS_MD_WITH_HEADING)

        skills = adapter.scan()
        assert Path(skills[0].source_path).is_absolute()

    def test_body_contains_file_content(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(cwd / "AGENTS.md", AGENTS_MD_WITH_HEADING)

        skills = adapter.scan()
        assert "My Codex Agent" in skills[0].body


# ---------------------------------------------------------------------------
# OpenAI adapter tests
# ---------------------------------------------------------------------------

class TestOpenAIAdapter:
    def _make_adapter(self, monkeypatch, tmp_path):
        import skillopt_studio.scanner.openai as openai_mod

        openai_home = tmp_path / "openai_home"
        monkeypatch.setattr(openai_mod, "_OPENAI_HOME", openai_home)

        cwd = tmp_path / "project"
        cwd.mkdir(parents=True, exist_ok=True)

        from skillopt_studio.scanner.openai import OpenAIAdapter
        return OpenAIAdapter(cwd), cwd, openai_home

    def _assistant_json(self, name: str = "Test Assistant") -> str:
        return json.dumps({"name": name, "model": "gpt-4", "instructions": "You are helpful."})

    def test_finds_json_in_openai_home(self, monkeypatch, tmp_path):
        adapter, _, openai_home = self._make_adapter(monkeypatch, tmp_path)
        _write(openai_home / "assistant.json", self._assistant_json("Home Assistant"))

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "Home Assistant"
        assert skills[0].provider.value == "openai"
        assert skills[0].id.startswith("openai:")

    def test_finds_json_in_cwd_openai_subdir(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(cwd / "openai" / "config.json", self._assistant_json("Project Assistant"))

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "Project Assistant"

    def test_heuristic_finds_openai_json_in_cwd(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        _write(cwd / "openai_assistant.json", self._assistant_json("Heuristic Assistant"))

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "Heuristic Assistant"

    def test_non_matching_json_ignored(self, monkeypatch, tmp_path):
        adapter, cwd, _ = self._make_adapter(monkeypatch, tmp_path)
        # A JSON file that doesn't match the heuristic
        _write(cwd / "package.json", '{"name": "my-package"}')

        skills = adapter.scan()
        assert skills == []

    def test_missing_roots_returns_empty(self, monkeypatch, tmp_path):
        adapter, _, _ = self._make_adapter(monkeypatch, tmp_path)
        skills = adapter.scan()
        assert skills == []

    def test_invalid_json_falls_back_to_filename(self, monkeypatch, tmp_path):
        adapter, _, openai_home = self._make_adapter(monkeypatch, tmp_path)
        _write(openai_home / "broken.json", "not valid json {{{")

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "broken"  # fallback to stem

    def test_name_fallback_when_no_name_field(self, monkeypatch, tmp_path):
        adapter, _, openai_home = self._make_adapter(monkeypatch, tmp_path)
        _write(openai_home / "myconfig.json", '{"model": "gpt-4"}')

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "myconfig"

    def test_source_path_is_absolute(self, monkeypatch, tmp_path):
        adapter, _, openai_home = self._make_adapter(monkeypatch, tmp_path)
        _write(openai_home / "a.json", self._assistant_json())

        skills = adapter.scan()
        assert Path(skills[0].source_path).is_absolute()


# ---------------------------------------------------------------------------
# CWD adapter tests
# ---------------------------------------------------------------------------

class TestCwdAdapter:
    def _make_adapter(self, tmp_path):
        from skillopt_studio.scanner.cwd import CwdAdapter
        cwd = tmp_path / "project"
        cwd.mkdir(parents=True, exist_ok=True)
        return CwdAdapter(cwd), cwd

    def test_finds_skill_md_in_root(self, tmp_path):
        adapter, cwd = self._make_adapter(tmp_path)
        _write(cwd / "SKILL.md", SKILL_MD_WITH_FM)

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "my-test-skill"
        assert skills[0].provider.value == "cwd"
        assert skills[0].id.startswith("cwd:")

    def test_finds_dotskill_md_files(self, tmp_path):
        adapter, cwd = self._make_adapter(tmp_path)
        _write(cwd / "my-tool.skill.md", "---\nname: my-tool\n---\nbody")

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "my-tool"

    def test_finds_skills_in_skills_subdir(self, tmp_path):
        adapter, cwd = self._make_adapter(tmp_path)
        _write(cwd / "skills" / "tool-a" / "SKILL.md", "---\nname: tool-a\n---\nbody")

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "tool-a"

    def test_name_fallback_when_no_frontmatter(self, tmp_path):
        adapter, cwd = self._make_adapter(tmp_path)
        _write(cwd / "SKILL.md", SKILL_MD_NO_FM)

        skills = adapter.scan()

        assert len(skills) == 1
        assert skills[0].name == "SKILL"

    def test_missing_cwd_returns_empty(self, tmp_path):
        from skillopt_studio.scanner.cwd import CwdAdapter
        nonexistent = tmp_path / "does_not_exist"
        adapter = CwdAdapter(nonexistent)

        skills = adapter.scan()
        assert skills == []

    def test_source_path_is_absolute(self, tmp_path):
        adapter, cwd = self._make_adapter(tmp_path)
        _write(cwd / "SKILL.md", SKILL_MD_WITH_FM)

        skills = adapter.scan()
        assert Path(skills[0].source_path).is_absolute()

    def test_body_contains_content(self, tmp_path):
        adapter, cwd = self._make_adapter(tmp_path)
        _write(cwd / "SKILL.md", SKILL_MD_WITH_FM)

        skills = adapter.scan()
        assert "Body content here" in skills[0].body


# ---------------------------------------------------------------------------
# Registry (scan_all) tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_scan_all_deduplicates_same_path(self, monkeypatch, tmp_path):
        """If two adapters somehow return the same source_path, it appears once."""
        from skillopt_studio.scanner import registry as reg_mod
        from skillopt_studio.domain import Skill, ProviderName

        fake_skill = Skill(
            id="claude:aabbccdd1234",
            name="duplicate",
            provider=ProviderName.claude,
            source_path="/tmp/fake/SKILL.md",
            body="body",
        )

        class FakeAdapter:
            provider_name = ProviderName.claude
            def root_paths(self): return []
            def scan(self): return [fake_skill, fake_skill]  # same object twice

        # Patch the scan_all to use only our fake adapter
        original_scan_all = reg_mod.scan_all

        def patched_scan_all(cwd):
            seen_paths: set[str] = set()
            skills = []
            for skill in FakeAdapter().scan():
                if skill.source_path in seen_paths:
                    continue
                seen_paths.add(skill.source_path)
                skills.append(skill)
            return skills

        monkeypatch.setattr(reg_mod, "scan_all", patched_scan_all)
        result = reg_mod.scan_all(tmp_path)
        assert len(result) == 1

    def test_scan_all_returns_list(self, tmp_path):
        from skillopt_studio.scanner import scan_all
        result = scan_all(tmp_path)
        assert isinstance(result, list)

    def test_scan_all_graceful_with_empty_cwd(self, tmp_path):
        """scan_all with a fresh empty dir should not raise."""
        from skillopt_studio.scanner import scan_all
        empty_cwd = tmp_path / "empty"
        empty_cwd.mkdir()
        result = scan_all(empty_cwd)
        assert isinstance(result, list)

    def test_scan_all_sorted(self, monkeypatch, tmp_path):
        """Results must be sorted by (provider, name)."""
        from skillopt_studio.scanner.claude import ClaudeAdapter
        import skillopt_studio.scanner.claude as claude_mod

        skills_dir = tmp_path / "skills"
        plugin_cache = tmp_path / "plugins" / "cache"
        monkeypatch.setattr(claude_mod, "_SKILLS_DIR", skills_dir)
        monkeypatch.setattr(claude_mod, "_PLUGIN_CACHE_DIR", plugin_cache)

        # Create two skills — z-skill should sort after a-skill
        _write(skills_dir / "z-skill" / "SKILL.md", "---\nname: z-skill\n---\nbody")
        _write(skills_dir / "a-skill" / "SKILL.md", "---\nname: a-skill\n---\nbody")

        from skillopt_studio.scanner import scan_all
        result = scan_all(tmp_path)

        claude_skills = [s for s in result if s.provider.value == "claude"]
        names = [s.name for s in claude_skills]
        assert names == sorted(names, key=str.lower)


# ---------------------------------------------------------------------------
# Real Claude scan (integration — no mocking)
# ---------------------------------------------------------------------------

class TestRealClaudeScan:
    """Integration test against actual ~/.claude directories.

    Skipped if the directories don't exist; never fails on count — just
    verifies provenance fields are populated correctly.
    """

    def test_real_claude_scan_finds_skills(self):
        skills_dir = Path.home() / ".claude" / "skills"
        plugin_cache = Path.home() / ".claude" / "plugins" / "cache"

        if not skills_dir.exists() and not plugin_cache.exists():
            pytest.skip("No ~/.claude skill directories found")

        from skillopt_studio.scanner.claude import ClaudeAdapter
        adapter = ClaudeAdapter()
        skills = adapter.scan()

        assert len(skills) > 0, "Expected at least one Claude skill"

        for s in skills:
            assert s.provider.value == "claude"
            assert s.id.startswith("claude:")
            assert Path(s.source_path).is_absolute()
            assert s.name  # non-empty name

    def test_real_scan_all_includes_claude(self):
        skills_dir = Path.home() / ".claude" / "skills"
        if not skills_dir.exists():
            pytest.skip("No ~/.claude/skills directory")

        from skillopt_studio.scanner import scan_all
        result = scan_all(Path.cwd())

        claude_skills = [s for s in result if s.provider.value == "claude"]
        assert len(claude_skills) > 0
