"""Dev tools stay inside the same size limits as the library."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _wad_diff():
    spec = importlib.util.spec_from_file_location("wad_diff", ROOT / "tools" / "wad_diff.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wad_diff_refuses_a_huge_file_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _wad_diff()
    reads: list[Path] = []
    real = Path.read_bytes

    def spy(self: Path) -> bytes:
        reads.append(self)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    monkeypatch.setattr(module, "_LIMIT", 4)
    left = tmp_path / "a.wad"
    right = tmp_path / "b.wad"
    left.write_bytes(b"abcde")
    right.write_bytes(b"abcd")
    with pytest.raises(SystemExit):
        module._load(left)
    assert reads == []


def _dol_diff():
    spec = importlib.util.spec_from_file_location("dol_diff", ROOT / "tools" / "dol_diff.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dol_diff_refuses_a_huge_file_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _dol_diff()
    reads: list[Path] = []
    real = Path.read_bytes

    def spy(self: Path) -> bytes:
        reads.append(self)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    monkeypatch.setattr(module, "_LIMIT", 4)
    left = tmp_path / "a.dol"
    right = tmp_path / "b.dol"
    left.write_bytes(b"abcde")
    right.write_bytes(b"abcd")
    with pytest.raises(SystemExit):
        module.main(["dol_diff", str(left), str(right)])
    assert reads == []
