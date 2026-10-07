"""The patcher requires the measured WiiGSC 1.1 slot, then changes exactly six bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from tests.support import synthetic_dol

from wiishortcut.errors import InvalidForwarderError, InvalidGameIDError, UnsupportedSourceError
from wiishortcut.forwarder.usbloadergx import (
    DISC_ID_DELTA,
    patch_usbloadergx,
    read_patched_game_id,
)

USB = Path("/tmp/wiishortcut-research/release/Loaders/USBLoaderGXForwarder.dol")
SD = Path("/tmp/wiishortcut-research/release/Loaders/USBLoaderGXForwarderSD.dol")
USB_SHA = "ff31340547ddf9eaad6ccc10491333fe59770d0fe978fc233e504c0399d7d671"
SD_SHA = "7702a375d7bd35354e51997c14f861f42e369e706fc8c1704b9b2d7cb1302cfb"


def test_patch_replaces_one_placeholder_and_keeps_the_config_block() -> None:
    original = synthetic_dol("usb")
    patched = patch_usbloadergx(original, "rmce01", "usb")
    assert original != patched
    assert patched.count(b"CRAPPY") == 0
    assert patched.count(b"CFGUGX") == 1
    assert patched.count(b"TCRP") == original.count(b"TCRP")
    assert b"--sdmode=1" not in patched
    assert read_patched_game_id(patched) == "RMCE01"
    config = patched.find(b"CFGUGX")
    assert patched[config + DISC_ID_DELTA : config + DISC_ID_DELTA + 6] == b"RMCE01"


def test_sd_patch_requires_the_sd_argument() -> None:
    patched = patch_usbloadergx(synthetic_dol("sd"), "RSBE01", "SD")
    assert patched.count(b"--sdmode=1") == 1
    assert read_patched_game_id(patched) == "RSBE01"
    with pytest.raises(InvalidForwarderError):
        patch_usbloadergx(synthetic_dol("usb"), "RSBE01", "sd")
    with pytest.raises(InvalidForwarderError):
        patch_usbloadergx(synthetic_dol("sd"), "RSBE01", "usb")


def test_patch_rejects_a_broken_layout() -> None:
    with pytest.raises(UnsupportedSourceError):
        patch_usbloadergx(synthetic_dol(), "RMCE01", "dvd")
    with pytest.raises(InvalidGameIDError):
        patch_usbloadergx(synthetic_dol(), "CRAPPY", "usb")
    broken = synthetic_dol() + b"CRAPPY"
    with pytest.raises(InvalidForwarderError, match="exactly one"):
        patch_usbloadergx(broken, "RMCE01", "usb")
    bad = b"CFGUGX" + synthetic_dol().replace(b"CFGUGX", b"XXXXXX", 1)
    with pytest.raises(InvalidForwarderError):
        patch_usbloadergx(bad, "RMCE01", "usb")
    with pytest.raises(InvalidForwarderError):
        patch_usbloadergx(b"", "RMCE01", "usb")


def test_missing_loader_path_is_rejected() -> None:
    raw = synthetic_dol().replace(b"apps/usbloadergx/boot.dol", b"apps/not-the-loader/boot")
    with pytest.raises(InvalidForwarderError, match="usbloadergx"):
        patch_usbloadergx(raw, "RMCE01", "usb")


@pytest.mark.skipif(not USB.is_file() or not SD.is_file(), reason="local WiiGSC 1.1 DOL is absent")
def test_real_wii_gsc_forwarders_match_the_manifest_and_patch() -> None:
    usb = USB.read_bytes()
    sd = SD.read_bytes()
    assert hashlib.sha256(usb).hexdigest() == USB_SHA
    assert hashlib.sha256(sd).hexdigest() == SD_SHA
    assert usb.count(b"CRAPPY") == 1
    assert sd.count(b"--sdmode=1") == 1
    assert usb.count(b"--sdmode=1") == 0
    patched = patch_usbloadergx(usb, "RMCE01", "usb")
    assert read_patched_game_id(patched) == "RMCE01"
    assert USB.read_bytes() == usb
    patched_sd = patch_usbloadergx(sd, "RMGE01", "sd")
    assert read_patched_game_id(patched_sd) == "RMGE01"
    assert patched_sd.count(b"--sdmode=1") == 1
