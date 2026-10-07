"""CLI behavior, exit codes, and the promise that a dry run writes nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.support import synthetic_dol, write_iso, write_wbfs
from typer.testing import CliRunner

from wiishortcut.cli import app
from wiishortcut.errors import InvalidOptionError
from wiishortcut.forwarder.assets import asset_for
from wiishortcut.forwarder.usbloadergx import patch_usbloadergx
from wiishortcut.pipeline import create_shortcut, run_batch

runner = CliRunner()


@pytest.fixture
def fake_forwarder(monkeypatch: pytest.MonkeyPatch):
    def resolve(**kwargs):
        data = synthetic_dol(kwargs["source"])
        return data, "ab" * 32

    monkeypatch.setattr("wiishortcut.pipeline.resolve_forwarder", resolve)


def test_help_and_version() -> None:
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "create" in help_result.stdout
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert "wiishortcut 0.1.0" in version.stdout
    assert "libWiiPy" in version.stdout


def test_inspect_wbfs_and_json(isolated: Path) -> None:
    image = write_wbfs(
        isolated / "Mario Kart Wii [RMCE01]" / "RMCE01.wbfs",
        "RMCE01",
        "Mario Kart Wii",
    )
    result = runner.invoke(app, ["inspect", str(image)])
    assert result.exit_code == 0
    assert "Game ID: RMCE01" in result.stdout
    assert "Title: Mario Kart Wii" in result.stdout
    assert "Region: USA" in result.stdout
    assert "Detected source: USB" in result.stdout
    payload = json.loads(runner.invoke(app, ["--debug", "inspect", str(image), "--json"]).stdout)
    assert payload["game_id"] == "RMCE01"
    assert payload["id_source"] == "wbfs-header"
    assert "ebe4" not in result.stdout


def test_inspect_corrupt_file_exits_2(isolated: Path) -> None:
    image = isolated / "Mario Kart Wii [RMCE01]" / "RMCE01.wbfs"
    image.parent.mkdir()
    image.write_bytes(b"nope")
    result = runner.invoke(app, ["inspect", str(image)])
    assert result.exit_code == 2
    assert "Unable to determine the Wii Game ID." in result.stderr
    assert "Traceback" not in result.stderr
    debug = runner.invoke(app, ["--debug", "inspect", str(image)])
    assert debug.exit_code == 2
    assert "Traceback" in debug.stderr


def test_create_validate_and_batch(isolated: Path, fake_forwarder: None) -> None:
    image = write_wbfs(
        isolated / "games" / "Mario Kart Wii [RMCE01]" / "RMCE01.wbfs",
        "RMCE01",
        "Mario Kart Wii",
    )
    other = write_iso(isolated / "games" / "galaxy.iso", "RMGE01", "Super Mario Galaxy")
    created = runner.invoke(app, ["create", str(image), "--json"])
    assert created.exit_code == 0, created.stderr
    payload = json.loads(created.stdout)
    assert payload["game_id"] == "RMCE01"
    assert payload["channel_id"] == "UMCE"
    assert payload["loader"] == "usbloadergx"
    assert payload["source"] == "usb"
    wad = Path(payload["output"])
    assert wad.is_file()
    before = image.read_bytes()
    validated = runner.invoke(app, ["validate", str(wad), "--strict"])
    assert validated.exit_code == 0, validated.stdout
    assert "VALID" in validated.stdout
    assert image.read_bytes() == before
    inspected = runner.invoke(app, ["wad", "inspect", str(wad)])
    assert inspected.exit_code == 0
    assert "UMCE" in inspected.stdout
    assert "Mario Kart Wii" in inspected.stdout
    dry = runner.invoke(
        app,
        ["batch", str(isolated / "games"), "--output", str(isolated / "out"), "--dry-run"],
    )
    assert dry.exit_code == 0, dry.stderr
    assert "Found 2 games." in dry.stdout
    assert "RMCE01 Mario Kart Wii" in dry.stdout
    assert "RMGE01 Super Mario Galaxy" in dry.stdout
    assert "Would create 2 WAD files." in dry.stdout
    assert not (isolated / "out").exists()
    assert other.is_file()


def test_batch_collision_exits_5(isolated: Path) -> None:
    root = isolated / "games"
    write_wbfs(root / "a.wbfs", "RMCE01", "One")
    write_wbfs(root / "b.wbfs", "XMCE01", "Two")
    result = runner.invoke(
        app,
        ["batch", str(root), "--dry-run", "--output", str(isolated / "out")],
    )
    assert result.exit_code == 5
    assert "UMCE" in result.stderr
    assert not (isolated / "out").exists()


def test_create_without_a_forwarder_exits_3(isolated: Path) -> None:
    image = write_wbfs(isolated / "game.wbfs", "RMCE01", "Mario Kart Wii")
    result = runner.invoke(app, ["create", str(image), "--json"])
    assert result.exit_code == 3
    body = json.loads(result.stdout)
    assert body["exit_code"] == 3
    assert asset_for("usbloadergx", "usb").sha256 in body["message"]
    assert "assets install" in body["message"]


def test_ios_requires_advanced_and_strict_validate(isolated: Path, fake_forwarder: None) -> None:
    image = write_iso(isolated / "game.iso", "RMCE01", "Mario Kart Wii")
    refused = runner.invoke(app, ["create", str(image), "--ios", "56"])
    assert refused.exit_code == 2
    built = runner.invoke(
        app,
        [
            "create",
            str(image),
            "--ios",
            "56",
            "--advanced",
            "--output",
            str(isolated / "custom.wad"),
        ],
    )
    assert built.exit_code == 0, built.stderr
    strict = runner.invoke(app, ["validate", str(isolated / "custom.wad"), "--strict"])
    assert strict.exit_code == 4
    assert "INVALID" in strict.stdout
    relaxed = runner.invoke(app, ["validate", str(isolated / "custom.wad")])
    assert relaxed.exit_code == 0
    assert "WARN" in relaxed.stdout


def test_long_disc_title_asks_for_name(isolated: Path, fake_forwarder: None) -> None:
    image = write_iso(isolated / "long.iso", "RMCE01", "A" * 50)
    result = runner.invoke(app, ["create", str(image)])
    assert result.exit_code == 2
    assert "--name" in result.stderr
    named = runner.invoke(app, ["create", str(image), "--name", "Short Title"])
    assert named.exit_code == 0, named.stderr


def test_doctor_and_assets(isolated: Path) -> None:
    doctor = runner.invoke(app, ["doctor", "--json"])
    assert doctor.exit_code == 0
    payload = json.loads(doctor.stdout)
    assert payload["forwarder"] == "missing"
    assert payload["ok"] is False
    assert payload["keys"] == "libWiiPy"
    human = runner.invoke(app, ["doctor"])
    assert human.exit_code == 0
    assert "USB GX forwarder  MISSING" in human.stdout
    listed = runner.invoke(app, ["assets", "list"])
    assert listed.exit_code == 0
    assert "forwarder-usb-v1" in listed.stdout
    assert "included no" in listed.stdout
    verified = runner.invoke(app, ["assets", "verify"])
    assert verified.exit_code == 3
    (isolated / "nope.dol").write_bytes(b"nope")
    refused = runner.invoke(app, ["assets", "install", str(isolated / "nope.dol")])
    assert refused.exit_code == 3


def test_existing_output_is_not_overwritten(isolated: Path, fake_forwarder: None) -> None:
    image = write_wbfs(isolated / "game.wbfs", "RMCE01", "Mario Kart Wii")
    target = isolated / "out.wad"
    target.write_bytes(b"keep")
    result = runner.invoke(app, ["create", str(image), "--output", str(target)])
    assert result.exit_code == 2
    assert target.read_bytes() == b"keep"


def test_debug_create_does_not_print_a_title_key(isolated: Path, fake_forwarder: None) -> None:
    image = write_iso(isolated / "game.iso", "RMCE01", "Mario Kart Wii")
    result = runner.invoke(app, ["-vv", "create", str(image), "--output", str(isolated / "a.wad")])
    assert result.exit_code == 0, result.stderr
    assert "title key" not in result.stderr.lower()
    assert "debug: patched game id" in result.stderr


def test_pipeline_leaves_the_image_unchanged(isolated: Path, fake_forwarder: None) -> None:
    image = write_wbfs(
        isolated / "Donkey Kong Country Returns [SF8E01]" / "SF8E01.wbfs",
        "SF8E01",
        "Donkey Kong",
    )
    before = hashlib_file(image)
    result = create_shortcut(image, output=isolated / "dk.wad")
    assert result.channel_id == "UF8E"
    assert hashlib_file(image) == before
    patched = patch_usbloadergx(synthetic_dol(), "SF8E01", "usb")
    assert patched[0:6] != b"SF8E01"


def test_doctor_survives_a_broken_keys_file(isolated: Path) -> None:
    (isolated / "config" / "keys.toml").write_text("[\n", encoding="utf-8")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["keys"] == "mismatch"
    assert "Traceback" not in result.stderr


def test_wad_inspect_refuses_an_oversize_file(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("wiishortcut.pipeline.MAX_WAD_BYTES", 32)
    path = isolated / "big.wad"
    path.write_bytes(b"x" * 64)
    result = runner.invoke(app, ["wad", "inspect", str(path)])
    assert result.exit_code == 4
    assert "32" in result.stderr


def test_wad_inspect_returns_validation_failure(isolated: Path, fake_forwarder: None) -> None:
    image = write_wbfs(isolated / "game.wbfs", "RMCE01", "Mario Kart Wii")
    built = runner.invoke(app, ["create", str(image), "--output", str(isolated / "ok.wad")])
    assert built.exit_code == 0, built.stderr
    raw = (isolated / "ok.wad").read_bytes()
    bad = isolated / "bad.wad"
    from wiishortcut.wad.validator import validate_wad

    chosen = raw
    for offset in range(len(raw) - 1, 0x40, -1):
        trial = bytearray(raw)
        trial[offset] ^= 0xFF
        report = validate_wad(bytes(trial))
        if any(check.label == "SHA-1" and check.state == "FAIL" for check in report.checks):
            chosen = bytes(trial)
            break
    bad.write_bytes(chosen)
    result = runner.invoke(app, ["wad", "inspect", str(bad)])
    assert result.exit_code == 4
    assert "Traceback" not in result.stderr


def test_manifest_sidecar_is_not_overwritten(isolated: Path, fake_forwarder: None) -> None:
    image = write_wbfs(isolated / "game.wbfs", "RMCE01", "Mario Kart Wii")
    sidecar = isolated / "out.wad.json"
    sidecar.write_text("keep\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["create", str(image), "--output", str(isolated / "out.wad"), "--manifest"],
    )
    assert result.exit_code == 2
    assert sidecar.read_text(encoding="utf-8") == "keep\n"
    assert not (isolated / "out.wad").exists()


def test_batch_forwards_the_advanced_flag(
    isolated: Path, fake_forwarder: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wiishortcut.pipeline import _check_ios

    calls: list[bool] = []
    real = _check_ios

    def wrapped(ios: int, advanced: bool) -> None:
        calls.append(advanced)
        if len(calls) == 1:
            return
        real(ios, advanced)

    monkeypatch.setattr("wiishortcut.pipeline._check_ios", wrapped)
    write_wbfs(isolated / "games" / "a.wbfs", "RMCE01", "One")
    with pytest.raises(InvalidOptionError):
        run_batch(isolated / "games", isolated / "out", ios=56, advanced=False)
    assert calls == [False, False]


def hashlib_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
