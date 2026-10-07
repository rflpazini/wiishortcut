"""Keep tests away from the real Application Support directory."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("WIISHORTCUT_CONFIG", str(config))
    monkeypatch.delenv("WII_COMMON_KEY_HEX", raising=False)
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
