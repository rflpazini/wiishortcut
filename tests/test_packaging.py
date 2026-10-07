"""The macOS release build must target arm64 and carry the package data."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _build_module():
    spec = importlib.util.spec_from_file_location(
        "build_macos_arm64", ROOT / "scripts" / "build_macos_arm64.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_command_targets_arm64_and_collects_package_data() -> None:
    module = _build_module()
    command = module.build_command(python="/usr/bin/python3")
    assert command[0] == "/usr/bin/python3"
    assert "--target-arch" in command
    assert command[command.index("--target-arch") + 1] == "arm64"
    collected = [command[index + 1] for index, arg in enumerate(command) if arg == "--collect-all"]
    assert collected == ["wiishortcut", "libWiiPy"]
    assert command[command.index("--distpath") + 1].endswith("/dist")
    assert command[command.index("--specpath") + 1].endswith("/build")
    assert command[-1].endswith("packaging/entry.py")
    assert "--onefile" in command


def test_build_refuses_a_non_arm64_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _build_module()
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PyInstaller ran")

    monkeypatch.setattr(module.subprocess, "run", refuse)
    assert module.main() == 2


def test_only_a_thin_arm64_binary_is_accepted() -> None:
    module = _build_module()
    assert module.is_thin_arm64("arm64\n")
    assert not module.is_thin_arm64("x86_64 arm64\n")
    assert not module.is_thin_arm64("x86_64\n")
    assert not module.is_thin_arm64("arm64 extra\n")


def test_a_universal_binary_is_deleted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _build_module()
    binary = tmp_path / "wiishortcut"
    binary.write_bytes(b"not a real macho")

    def fake_run(command: list[str], **_kwargs: object) -> object:
        class Result:
            stdout = "Mach-O universal\n" if command[0] == "file" else "x86_64 arm64\n"

        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.verify_binary(binary) == 1
    assert not binary.exists()


def test_entry_point_has_no_forwarder_or_common_key() -> None:
    text = (ROOT / "packaging" / "entry.py").read_text(encoding="utf-8").lower()
    assert ".dol" not in text
    assert "ebe42a22" + "5e8593e4" + "48d9c545" + "7381aaf7" not in text
    assert "download_title" not in text
