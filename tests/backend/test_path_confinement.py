"""Workspace path-confinement tests (#10)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from skillopt_studio.api.runs import _confined


class TestConfined:
    def test_inside_root_ok(self, tmp_path):
        f = tmp_path / "sub" / "file.md"
        f.parent.mkdir(parents=True)
        f.write_text("x", encoding="utf-8")
        resolved = _confined(f, tmp_path)
        assert resolved == f.resolve()

    def test_escape_via_dotdot_rejected(self, tmp_path):
        root = tmp_path / "workspace"
        root.mkdir()
        with pytest.raises(HTTPException) as ei:
            _confined(root / ".." / "etc" / "passwd", root)
        assert ei.value.status_code == 400

    def test_absolute_outside_rejected(self, tmp_path):
        root = tmp_path / "workspace"
        root.mkdir()
        with pytest.raises(HTTPException) as ei:
            _confined("/etc/hosts", root)
        assert ei.value.status_code == 400
