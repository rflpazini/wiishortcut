"""Config, keys, and forwarder assets. Key bytes are never asserted into a message."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from tests.support import synthetic_dol

from wiishortcut.config import assert_common_key, key_status, load_config
from wiishortcut.errors import AssetIntegrityError, ConfigError, MissingKeyError
from wiishortcut.forwarder.assets import (
    Asset,
    accept_forwarder,
    asset_for,
    install_asset,
    load_manifest,
    resolve_forwarder,
)


def test_huge_forwarder_is_refused_before_it_is_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("wiishortcut.forwarder.usbloadergx.MAX_FORWARDER_BYTES", 8)
    path = tmp_path / "big.dol"
    path.write_bytes(b"x" * 9)
    with pytest.raises(AssetIntegrityError, match="limit"):
        resolve_forwarder(
            loader="usbloadergx",
            source="usb",
            assets_dir=tmp_path,
            explicit=path,
        )


def test_unreadable_forwarder_is_a_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wiishortcut.forwarder.assets import verify_installed

    asset = asset_for("usbloadergx", "usb")
    (tmp_path / asset.filename).write_bytes(b"x")

    def boom(self: Path) -> bytes:
        raise OSError("denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    rows = {item.name: status for item, status in verify_installed(tmp_path)}
    assert rows["forwarder-usb-v1"] == "mismatch"


def test_manifest_is_packaged_and_does_not_ship_the_dol() -> None:
    manifest = load_manifest()
    usb = manifest["forwarder-usb-v1"]
    sd = manifest["forwarder-sd-v1"]
    assert usb.included is False
    assert sd.included is False
    assert usb.bootable is True
    assert sd.bootable is True
    assert asset_for("usbloadergx", "usb").sha256 == usb.sha256
    assert asset_for("usbloadergx", "sd").filename.endswith("SD.dol")


def test_missing_forwarder_names_the_expected_hash(isolated: Path) -> None:
    with pytest.raises(AssetIntegrityError, match="assets install") as caught:
        resolve_forwarder(
            loader="usbloadergx",
            source="usb",
            assets_dir=isolated / "config" / "assets",
        )
    assert asset_for("usbloadergx", "usb").sha256 in str(caught.value)


def test_random_file_is_refused(isolated: Path) -> None:
    source = isolated / "nope.dol"
    source.write_bytes(synthetic_dol())
    with pytest.raises(AssetIntegrityError, match="not a known"):
        install_asset(source, isolated / "config" / "assets")


def test_unbootable_record_is_refused() -> None:
    asset = Asset(
        name="fixture",
        sha256=hashlib.sha256(b"dol").hexdigest(),
        filename="fixture.dol",
        source="test",
        license="test",
        included=False,
        platform="wii",
        loader="usbloadergx",
        source_device="usb",
        bootable=False,
    )
    with pytest.raises(AssetIntegrityError, match="not marked bootable"):
        accept_forwarder(b"dol", asset)


def test_defaults_and_a_key_must_not_live_in_config_toml(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config()
    assert config.loader == "usbloadergx"
    assert config.source == "usb"
    assert config.ios == 58
    assert key_status() == "libWiiPy"
    assert_common_key()
    path = isolated / "config" / "config.toml"
    path.write_text('default_ios = 58\ncommon_key_hex = "aa"\n', encoding="utf-8")
    with pytest.raises(MissingKeyError, match="config.toml"):
        load_config()
    path.write_text("default_ios = true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()
    path.write_text("[\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config()
    path.write_text('[keys]\ncommon_key_hex = "aa"\n', encoding="utf-8")
    with pytest.raises(MissingKeyError, match="config.toml"):
        load_config()
    path.unlink()
    (isolated / "config" / "keys.toml").write_text("[\n", encoding="utf-8")
    assert key_status() == "mismatch"
    monkeypatch.setenv("WII_COMMON_KEY_HEX", "zz")
    assert key_status() == "mismatch"
    with pytest.raises(MissingKeyError):
        assert_common_key()


def test_matching_key_is_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    from libWiiPy.title.commonkeys import get_common_key

    library = get_common_key(0, False)
    monkeypatch.setenv("WII_COMMON_KEY_HEX", library.hex())
    assert key_status() == "configured"
    assert_common_key()
