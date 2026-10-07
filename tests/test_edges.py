"""Error paths, batch builds, and the checks a hostile file must not skip."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.support import disc_header, synthetic_dol, write_iso, write_wbfs
from typer.testing import CliRunner

from wiishortcut.channel.banner import (
    build_static_banner,
    imd5_wrap,
    imet_md5_matches,
    retitle_banner,
)
from wiishortcut.channel.builder import assemble_channel
from wiishortcut.channel.title_id import channel_id_from_title_id, full_title_id
from wiishortcut.cli import _output_writable, _rosetta, app
from wiishortcut.config import (
    _bytes_equal,
    _key_from_files,
    _supplied_key,
    application_support_dir,
    cache_dir,
    key_status,
    load_config,
)
from wiishortcut.errors import (
    AssetIntegrityError,
    ConfigError,
    InvalidForwarderError,
    InvalidGameIDError,
    InvalidGameImageError,
    InvalidOptionError,
    InvalidWadError,
    MissingKeyError,
    OutputExistsError,
    UnsupportedLoaderError,
    UnsupportedSourceError,
)
from wiishortcut.forwarder.assets import (
    Asset,
    asset_for,
    install_asset,
    resolve_forwarder,
    verify_installed,
)
from wiishortcut.forwarder.usbloadergx import (
    detect_source,
    patch_usbloadergx,
    read_patched_game_id,
)
from wiishortcut.game.detect import detect_game, read_image, title_from_path
from wiishortcut.game.iso import parse_disc_header, read_bounded
from wiishortcut.game.metadata import GameMetadata, region_from_game_id
from wiishortcut.game.wbfs import read_wbfs
from wiishortcut.pipeline import (
    _check_ios,
    create_shortcut,
    explicit_game_id,
    format_batch,
    format_create,
    format_dry_run,
    format_inspect,
    output_filename,
    plan_batch,
    run_batch,
    scan_library,
    validate_file,
)
from wiishortcut.wad.builder import build_wad
from wiishortcut.wad.dol import parse_dol
from wiishortcut.wad.validator import describe_wad, format_report, validate_wad

runner = CliRunner()
_MAGIC = bytes.fromhex("0000002049730000")


def _shell() -> bytes:
    data = bytearray(0x200)
    data[:8] = _MAGIC
    struct.pack_into(">IIIIII", data, 0x08, 64, 0, 64, 64, 64, 0)
    return bytes(data)


class _Record:
    def __init__(self, index: int, size: int, content_id: int = 0) -> None:
        self.index = index
        self.content_id = content_id
        self.content_type = 1
        self.content_size = size
        self.content_hash = b"ab" * 20


class _Title:
    def __init__(self, **kwargs: object) -> None:
        ticket = kwargs.get("ticket_id", bytes.fromhex("00010001554d4345"))
        self.ticket = SimpleNamespace(title_id=ticket)
        records = kwargs["records"]
        self.tmd = SimpleNamespace(
            title_id=kwargs.get("tmd_id", "00010001554d4345"),
            num_contents=kwargs.get("num", len(records)),  # type: ignore[arg-type]
            content_records=records,
            boot_index=kwargs.get("boot", 1),
            ios_version=kwargs.get("ios", 58),
            access_rights=kwargs.get("access", 3),
            title_version=1,
            region=3,
        )
        self._blobs = kwargs["blobs"]
        self._load_error = kwargs.get("load_error")
        self._get_error = kwargs.get("get_error")

    def load_wad(self, _data: bytes) -> None:
        if self._load_error is not None:
            raise self._load_error  # type: ignore[misc]

    def get_content_by_index(self, position: int) -> bytes:
        if self._get_error is not None:
            raise self._get_error  # type: ignore[misc]
        return self._blobs[position]  # type: ignore[index]


def _install(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> None:
    def factory() -> _Title:
        return _Title(**kwargs)

    monkeypatch.setattr("wiishortcut.wad.validator.Title", factory)


def _report(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> object:
    strict = bool(kwargs.pop("strict", False))
    blobs = kwargs.pop("blobs", None)
    if blobs is None:
        blobs = [
            build_static_banner("Game"),
            patch_usbloadergx(synthetic_dol(), "RMCE01", "usb"),
        ]
    records = kwargs.pop("records", None)
    if records is None:
        records = [
            _Record(0, len(blobs[0])),
            _Record(1, len(blobs[1]), content_id=1),
        ]
    _install(monkeypatch, records=records, blobs=blobs, **kwargs)
    return validate_wad(_shell(), strict=strict)


def _fake_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(**kwargs: object) -> tuple[bytes, str]:
        source = str(kwargs["source"])
        return synthetic_dol(source), "cd" * 32

    monkeypatch.setattr("wiishortcut.pipeline.resolve_forwarder", resolve)


def _asset(
    data: bytes,
    *,
    device: str = "usb",
    bootable: bool = True,
    filename: str = "USBLoaderGXForwarder.dol",
) -> Asset:
    return Asset(
        name=f"forwarder-{device}",
        sha256=hashlib.sha256(data).hexdigest(),
        filename=filename,
        source="test",
        license="test",
        included=False,
        platform="wii",
        loader="usbloadergx",
        source_device=device,
        bootable=bootable,
    )


def test_header_rejects_bad_magic_empty_sections_and_a_short_file() -> None:
    short = validate_wad(b"\x00" * 8)
    assert short.checks[0].state == "FAIL"
    assert format_report(short).endswith("INVALID")
    magic = validate_wad(b"\x00" * 0x40)
    assert "Is" in magic.checks[0].note
    empty = bytearray(0x40)
    empty[:8] = _MAGIC
    struct.pack_into(">IIIIII", empty, 0x08, 0, 0, 64, 64, 64, 0)
    missing = validate_wad(bytes(empty))
    assert "missing" in missing.checks[0].note
    tight = bytearray(0x40)
    tight[:8] = _MAGIC
    struct.pack_into(">IIIIII", tight, 0x08, 64, 0, 64, 64, 64, 0)
    overflow = validate_wad(bytes(tight))
    assert "does not fit" in overflow.checks[0].note
    with pytest.raises(InvalidWadError):
        describe_wad(b"\x00" * 8)


def test_header_rejects_an_unaligned_section_and_a_huge_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("wiishortcut.wad.validator.align", lambda value, boundary=0x40: value + 1)
    shifted = validate_wad(_shell())
    assert "aligned" in shifted.checks[0].note
    monkeypatch.setattr("wiishortcut.wad.validator.MAX_WAD_BYTES", 80)
    huge = validate_wad(b"\x00" * 100)
    assert "32 MiB" in huge.checks[0].note


def test_parser_errors_stay_on_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    class Blank(ValueError):
        def __str__(self) -> str:
            return ""

    _install(monkeypatch, records=[], blobs=[], load_error=Blank())
    blank = validate_wad(_shell())
    assert blank.checks[-1].note == "Blank"
    _install(monkeypatch, records=[], blobs=[], load_error=ValueError("x" * 400))
    long = validate_wad(_shell())
    assert long.checks[-1].note.endswith("...")
    assert len(long.checks[-1].note) < 200
    with pytest.raises(InvalidWadError, match="xxx"):
        describe_wad(_shell())


def test_title_id_mismatches_are_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    uneo = "00010001" + b"UNEO".hex()
    raw = "00010001ffffffff"
    cases = [
        ({"ticket_id": b"\x00" * 4}, "not 8 bytes"),
        ({"tmd_id": "00010001zzzzzzzz"}, "not hex"),
        ({"ticket_id": b"\x00" * 8}, "mismatch"),
        ({"tmd_id": uneo, "ticket_id": bytes.fromhex(uneo)}, "UNEO"),
        ({"tmd_id": raw, "ticket_id": bytes.fromhex(raw)}, "not hex"),
    ]
    for kwargs, expected in cases:
        report = _report(monkeypatch, **kwargs)
        failed = [check for check in report.checks if check.state == "FAIL"]
        assert failed
        assert expected in failed[-1].note


def test_content_table_and_hash_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = _report(
        monkeypatch,
        records=[_Record(0, 4), _Record(0, 4)],
        blobs=[b"abcd", b"abcd"],
    )
    assert any("Duplicate" in check.note for check in duplicate.checks)
    counted = _report(monkeypatch, num=3, records=[_Record(0, 4)], blobs=[b"abcd"])
    assert any("not usable" in check.note for check in counted.checks)
    boot = _report(monkeypatch, boot=9)
    assert any("Boot index" in check.note for check in boot.checks)
    banner = build_static_banner("Game")
    dol = patch_usbloadergx(synthetic_dol(), "RMCE01", "usb")
    mismatch = _report(
        monkeypatch,
        records=[_Record(0, 1), _Record(1, len(dol), 1)],
        blobs=[banner, dol],
    )
    assert any(check.label == "SHA-1" and check.state == "FAIL" for check in mismatch.checks)
    raised = _report(monkeypatch, get_error=ValueError("decrypt failed"))
    assert any(check.label == "SHA-1" and "decrypt failed" in check.note for check in raised.checks)


def test_banner_and_dol_failures_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    dol = patch_usbloadergx(synthetic_dol(), "RMCE01", "usb")
    missing = _report(
        monkeypatch,
        records=[_Record(1, len(dol), 1), _Record(2, 4, 2)],
        blobs=[dol, b"xxxx"],
        boot=1,
    )
    assert any(check.label == "opening.bnr" and check.state == "FAIL" for check in missing.checks)
    garbage = _report(monkeypatch, blobs=[b"\x00" * 0x800, dol])
    assert any("opening.bnr" == check.label and check.state == "FAIL" for check in garbage.checks)
    broken = bytearray(build_static_banner("Game"))
    broken[0x100] ^= 0x01
    hashed = _report(monkeypatch, blobs=[bytes(broken), dol])
    assert any(check.label == "IMET" and check.state == "FAIL" for check in hashed.checks)
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0x1C, 0x100)
    struct.pack_into(">I", header, 0x64, 0x80004000)
    struct.pack_into(">I", header, 0xAC, 4)
    struct.pack_into(">I", header, 0xE0, 0x80004000)
    plain = _report(monkeypatch, blobs=[build_static_banner("Game"), bytes(header) + b"xxxx"])
    assert any("markers" in check.note for check in plain.checks)
    placeholder = _report(monkeypatch, blobs=[build_static_banner("Game"), synthetic_dol()])
    assert any("game ID" in check.note for check in placeholder.checks)


def test_boot_content_must_be_index_1(monkeypatch: pytest.MonkeyPatch) -> None:
    banner = build_static_banner("Game")
    dol = patch_usbloadergx(synthetic_dol(), "RMCE01", "usb")
    records = [_Record(0, len(banner)), _Record(2, len(dol), content_id=1)]
    report = _report(monkeypatch, boot=2, records=records, blobs=[banner, dol])
    assert report.ok is False
    assert any(
        check.label == "Contents" and check.state == "FAIL" and "content 1" in check.note
        for check in report.checks
    )


def test_validate_rejects_a_u8_name_that_escapes(monkeypatch: pytest.MonkeyPatch) -> None:
    banner = bytearray(build_static_banner("Game"))
    start = banner.find(b"icon.bin")
    banner[start : start + len(b"icon.bin")] = b"../a.bin"
    dol = patch_usbloadergx(synthetic_dol(), "RMCE01", "usb")
    report = _report(monkeypatch, blobs=[bytes(banner), dol], strict=True)
    assert report.ok is False
    assert any(
        check.label == "opening.bnr" and check.state == "FAIL" and "relative path" in check.note
        for check in report.checks
    )


def test_validate_rejects_a_u8_node_table_without_loading_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    banner = bytearray(build_static_banner("Game"))
    banner[0x628:0x62C] = (8_000_000).to_bytes(4, "big")
    dol = patch_usbloadergx(synthetic_dol(), "RMCE01", "usb")

    def explode(self: object, _data: bytes) -> None:
        raise AssertionError("U8Archive.load ran")

    monkeypatch.setattr("wiishortcut.wad.validator.U8Archive.load", explode)
    report = _report(monkeypatch, blobs=[bytes(banner), dol])
    assert any(
        check.label == "opening.bnr" and check.state == "FAIL" and "node table" in check.note
        for check in report.checks
    )


def test_access_rights_warning_fails_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    relaxed = _report(monkeypatch, access=0)
    assert relaxed.ok
    assert any(check.state == "WARN" and check.label == "Access rights" for check in relaxed.checks)
    strict = _report(monkeypatch, access=0, strict=True)
    assert not strict.ok
    assert format_report(strict).endswith("INVALID")


def test_u8_names_must_stay_inside_the_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    from libWiiPy.archive.u8 import U8Archive

    real_load = U8Archive.load

    def escaped(self: U8Archive, data: bytes) -> None:
        real_load(self, data)
        self.file_name_list.append("../secret")

    monkeypatch.setattr("wiishortcut.wad.validator.U8Archive.load", escaped)
    report = _report(monkeypatch)
    assert any("relative path" in check.note for check in report.checks)

    def dotted(self: U8Archive, data: bytes) -> None:
        real_load(self, data)
        self.file_name_list = ["meta/./icon.bin"]

    monkeypatch.setattr("wiishortcut.wad.validator.U8Archive.load", dotted)
    dotted_report = _report(monkeypatch)
    assert any("relative path" in check.note for check in dotted_report.checks)


def test_describe_uses_an_empty_name_list(monkeypatch: pytest.MonkeyPatch) -> None:
    from libWiiPy.archive.u8 import IMETHeader

    wad = build_wad(
        banner=build_static_banner("Named"),
        dol=patch_usbloadergx(synthetic_dol(), "RMCE01", "usb"),
        channel_id="UMCE",
        game_id="RMCE01",
        loader="usbloadergx",
        source="usb",
        ios=58,
    )
    real_load = IMETHeader.load

    def nameless(self: IMETHeader, data: bytes) -> None:
        real_load(self, data)
        self.channel_names = []

    monkeypatch.setattr("wiishortcut.wad.validator.IMETHeader.load", nameless)
    info = describe_wad(wad)
    assert info["banner_name"] == ""
    assert info["channel_id"] == "UMCE"
    assert info["valid"] is True


def test_dol_sections_must_fit_and_have_an_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr("wiishortcut.wad.dol.MAX_DOL_BYTES", 0x100)
        with pytest.raises(InvalidWadError, match="8 MiB"):
            parse_dol(b"\x00" * 0x101)
    empty = bytearray(0x100)
    struct.pack_into(">I", empty, 0xE0, 1)
    with pytest.raises(InvalidWadError, match="no sections"):
        parse_dol(bytes(empty))
    inside = bytearray(0x110)
    struct.pack_into(">I", inside, 0x1C, 0x10)
    struct.pack_into(">I", inside, 0xAC, 4)
    struct.pack_into(">I", inside, 0xE0, 1)
    with pytest.raises(InvalidWadError, match="inside the header"):
        parse_dol(bytes(inside))
    overflow = bytearray(0x108)
    struct.pack_into(">I", overflow, 0x1C, 0x100)
    struct.pack_into(">I", overflow, 0xAC, 64)
    struct.pack_into(">I", overflow, 0xE0, 1)
    with pytest.raises(InvalidWadError, match="does not fit"):
        parse_dol(bytes(overflow))
    no_entry = bytearray(0x104)
    struct.pack_into(">I", no_entry, 0x1C, 0x100)
    struct.pack_into(">I", no_entry, 0xAC, 4)
    with pytest.raises(InvalidWadError, match="entry point"):
        parse_dol(bytes(no_entry))


def test_patch_rejects_a_moved_config_block_and_a_rewritten_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr("wiishortcut.forwarder.usbloadergx.MAX_FORWARDER_BYTES", 8)
        with pytest.raises(InvalidForwarderError, match="8 MiB"):
            patch_usbloadergx(synthetic_dol(), "RMCE01", "usb")
    without_config = synthetic_dol().replace(b"CFGUGX", b"XXXXXX")
    with pytest.raises(InvalidForwarderError, match="CFGUGX"):
        patch_usbloadergx(without_config, "RMCE01", "usb")
    with pytest.raises(InvalidForwarderError, match="config block"):
        patch_usbloadergx(synthetic_dol(), "CFGUGX", "usb")
    with pytest.raises(InvalidForwarderError, match="TCRP"):
        patch_usbloadergx(synthetic_dol(), "ABTCRP", "usb")
    with pytest.raises(InvalidForwarderError, match="exactly once"):
        read_patched_game_id(b"\x00" * 32)
    with pytest.raises(InvalidForwarderError, match="6-character"):
        read_patched_game_id(synthetic_dol())
    with pytest.raises(InvalidForwarderError, match="more than once"):
        detect_source(synthetic_dol("sd") + b"--sdmode=1")


def test_banner_refuses_a_broken_template(monkeypatch: pytest.MonkeyPatch) -> None:
    from libWiiPy.archive.u8 import IMETHeader

    monkeypatch.setattr("wiishortcut.channel.banner.MAX_BANNER_BYTES", 4)
    with pytest.raises(InvalidWadError, match="8 MiB"):
        imd5_wrap(b"12345")
    monkeypatch.undo()
    monkeypatch.setattr(IMETHeader, "dump", lambda self: b"\x00" * 0x600)
    with pytest.raises(InvalidWadError, match="IMET magic"):
        build_static_banner("Game")
    monkeypatch.undo()
    monkeypatch.setattr("wiishortcut.channel.banner.pack_u8", lambda root: b"\x00" * 16)
    with pytest.raises(InvalidWadError, match="U8"):
        build_static_banner("Game")


def test_retitle_checks_size_magic_and_the_u8(monkeypatch: pytest.MonkeyPatch) -> None:
    from libWiiPy.archive.u8 import IMETHeader

    original = build_static_banner("Old Name")
    with pytest.raises(InvalidWadError, match="between"):
        retitle_banner(b"\x00" * 16, "New")
    short_imet = bytearray(0x80)
    short_imet[0x40:0x44] = b"IMET"
    assert imet_md5_matches(bytes(short_imet)) is False
    with pytest.raises(InvalidWadError, match="no IMET"):
        retitle_banner(b"\x00" * 0x700, "New")
    shifted = b"\x00" * 0x40 + original
    updated = retitle_banner(shifted, "New Name")
    assert imet_md5_matches(updated)
    corrupt = bytearray(original)
    corrupt[0x600:0x604] = b"XXXX"
    with pytest.raises(InvalidWadError, match="U8"):
        retitle_banner(bytes(corrupt), "New")
    real_load = IMETHeader.load

    def wrong_magic(self: IMETHeader, data: bytes) -> None:
        real_load(self, data)
        self.magic = "NOPE"

    monkeypatch.setattr(IMETHeader, "load", wrong_magic)
    with pytest.raises(InvalidWadError, match="not IMET"):
        retitle_banner(original, "New")
    monkeypatch.undo()
    monkeypatch.setattr(IMETHeader, "dump", lambda self: b"IMET")
    with pytest.raises(InvalidWadError, match="1536"):
        retitle_banner(original, "New")


def test_retitle_rejects_a_u8_name_that_escapes(monkeypatch: pytest.MonkeyPatch) -> None:
    banner = bytearray(build_static_banner("Old"))
    start = banner.find(b"icon.bin")
    assert start > 0
    banner[start : start + len(b"icon.bin")] = b"../a.bin"

    def explode(self: object, _data: bytes) -> None:
        raise AssertionError("U8Archive.load ran")

    monkeypatch.setattr("wiishortcut.channel.banner.U8Archive.load", explode)
    with pytest.raises(InvalidWadError, match="relative path"):
        retitle_banner(bytes(banner), "New")


def test_retitle_rejects_a_node_table_that_does_not_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    banner = bytearray(build_static_banner("Old"))
    assert 1 <= int.from_bytes(banner[0x628:0x62C], "big") <= 16
    banner[0x628:0x62C] = (8_000_000).to_bytes(4, "big")

    def explode(self: object, _data: bytes) -> None:
        raise AssertionError("U8Archive.load ran")

    monkeypatch.setattr("wiishortcut.channel.banner.U8Archive.load", explode)
    with pytest.raises(InvalidWadError, match="node table"):
        retitle_banner(bytes(banner), "New")


def test_retitle_rejects_a_u8_name_without_a_nul(monkeypatch: pytest.MonkeyPatch) -> None:
    banner = bytearray(build_static_banner("Old"))
    count = int.from_bytes(banner[0x628:0x62C], "big")
    table_end = 0x600 + 0x20 + count * 12
    for index in range(table_end, len(banner)):
        if banner[index] == 0:
            banner[index] = 0x41

    def explode(self: object, _data: bytes) -> None:
        raise AssertionError("U8Archive.load ran")

    monkeypatch.setattr("wiishortcut.channel.banner.U8Archive.load", explode)
    with pytest.raises(InvalidWadError, match="NUL-terminated"):
        retitle_banner(bytes(banner), "New")


def test_assemble_channel_retitles_a_supplied_banner() -> None:
    files = assemble_channel(
        name="New Name",
        channel_id="abcd",
        ios=58,
        boot_dol=b"dol",
        banner=build_static_banner("Old Name"),
    )
    assert files.channel_id == "ABCD"
    assert files.name == "New Name"
    assert "New Name".encode("utf-16-be") in files.banner
    assert b"WIISHORTCUT-BANNER-V1" in files.banner


def test_title_id_hex_and_prefix_are_checked() -> None:
    with pytest.raises(InvalidGameIDError, match="not hex"):
        channel_id_from_title_id("00010001zzzzzzzz")
    with pytest.raises(InvalidGameIDError, match="8-digit"):
        full_title_id("UMCE", title_type="nope")


def test_build_rejects_bad_ios_empty_parts_and_a_failed_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libWiiPy.title.cert import CertificateChain
    from libWiiPy.title.ticket import Ticket

    kwargs = {
        "banner": build_static_banner("Game"),
        "dol": patch_usbloadergx(synthetic_dol(), "RMCE01", "usb"),
        "channel_id": "UMCE",
        "game_id": "RMCE01",
        "loader": "usbloadergx",
        "source": "usb",
        "ios": 58,
    }
    with pytest.raises(InvalidWadError, match="IOS"):
        build_wad(**{**kwargs, "ios": 2})
    with pytest.raises(InvalidWadError, match="required"):
        build_wad(**{**kwargs, "banner": b""})
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(2**64))
    with pytest.raises(InvalidWadError, match="out of range"):
        build_wad(**kwargs)
    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    monkeypatch.setattr("wiishortcut.wad.builder.MAX_WAD_BYTES", 1)
    with pytest.raises(InvalidWadError, match="32 MiB"):
        build_wad(**kwargs)
    monkeypatch.setattr("wiishortcut.wad.builder.MAX_WAD_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(Ticket, "dump", lambda self: b"")
    with pytest.raises(InvalidWadError, match="676"):
        build_wad(**kwargs)
    monkeypatch.undo()

    def broken_load(self: CertificateChain, data: bytes) -> None:
        raise ValueError("bad cert")

    monkeypatch.setattr(CertificateChain, "load", broken_load)
    with pytest.raises(InvalidWadError, match="certificate chain"):
        build_wad(**kwargs)
    monkeypatch.undo()
    monkeypatch.setattr("libWiiPy.title.tmd.TMD.get_is_fakesigned", lambda self: False)
    with pytest.raises(InvalidWadError, match="fakesign"):
        build_wad(**kwargs)


def test_base_wad_must_be_a_two_content_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    banner = build_static_banner("Game")
    dol = patch_usbloadergx(synthetic_dol(), "RMCE01", "usb")
    common = {
        "banner": banner,
        "dol": dol,
        "channel_id": "UMCE",
        "game_id": "RMCE01",
        "loader": "usbloadergx",
        "source": "usb",
        "ios": 58,
    }
    monkeypatch.setattr("wiishortcut.wad.builder.MAX_WAD_BYTES", 8)
    with pytest.raises(InvalidWadError, match="base WAD"):
        build_wad(**common, base_wad=b"\x00" * 9)
    monkeypatch.setattr("wiishortcut.wad.builder.MAX_WAD_BYTES", 32 * 1024 * 1024)

    class Broken:
        def load_wad(self, _data: bytes) -> None:
            raise ValueError("nope")

    monkeypatch.setattr("wiishortcut.wad.builder.Title", Broken)
    with pytest.raises(InvalidWadError, match="could not be parsed"):
        build_wad(**common, base_wad=b"\x00" * 64)

    class OneContent:
        def load_wad(self, _data: bytes) -> None:
            self.tmd = SimpleNamespace(num_contents=1, title_id="00010001554d4345")
            self.content = SimpleNamespace(content_records=[SimpleNamespace(index=0)])

    monkeypatch.setattr("wiishortcut.wad.builder.Title", OneContent)
    with pytest.raises(InvalidWadError, match="exactly 2"):
        build_wad(**common, base_wad=b"\x00" * 64)

    class WrongBoot:
        def load_wad(self, _data: bytes) -> None:
            self.tmd = SimpleNamespace(num_contents=2, title_id="00010001554d4345")
            self.content = SimpleNamespace(
                content_records=[SimpleNamespace(index=0), SimpleNamespace(index=2)]
            )

    monkeypatch.setattr("wiishortcut.wad.builder.Title", WrongBoot)
    with pytest.raises(InvalidWadError, match="content index 1"):
        build_wad(**common, base_wad=b"\x00" * 64)

    class ShortId:
        def load_wad(self, _data: bytes) -> None:
            self.tmd = SimpleNamespace(num_contents=2, title_id="abcd")
            self.content = SimpleNamespace(
                content_records=[SimpleNamespace(index=0), SimpleNamespace(index=1)]
            )

    monkeypatch.setattr("wiishortcut.wad.builder.Title", ShortId)
    with pytest.raises(InvalidWadError, match="4-byte"):
        build_wad(**common, base_wad=b"\x00" * 64)

    class Undecryptable:
        def load_wad(self, _data: bytes) -> None:
            self.tmd = SimpleNamespace(
                num_contents=2,
                title_id="00010001554d4345",
                ios_tid="",
                ios_version=0,
                access_rights=0,
                boot_index=0,
                vwii=0,
            )
            self.content = SimpleNamespace(
                content_records=[SimpleNamespace(index=0), SimpleNamespace(index=1)]
            )

        def set_title_id(self, _value: str) -> None:
            raise ValueError("decrypt")

    monkeypatch.setattr("wiishortcut.wad.builder.Title", Undecryptable)
    with pytest.raises(InvalidWadError, match="retail common key"):
        build_wad(**common, base_wad=b"\x00" * 64)


def test_a_generated_wad_can_be_reused_as_the_base(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_resolve(monkeypatch)
    image = write_iso(isolated / "game.iso", "RMCE01", "Mario Kart Wii")
    first = create_shortcut(image, output=isolated / "first.wad")
    second = create_shortcut(
        image,
        output=isolated / "second.wad",
        channel_id="ABCD",
        name="Renamed",
        base_wad=first.output,
    )
    report = validate_file(second.output)
    assert report.ok
    assert report.channel_id == "ABCD"
    assert report.game_id == "RMCE01"
    described = describe_wad(second.output.read_bytes())
    assert described["banner_name"] == "Renamed"


def test_image_readers_reject_the_remaining_bad_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert region_from_game_id("AB") is None
    assert title_from_path(Path("/game.wbfs")) is None
    assert title_from_path(Path("game.wbfs")) is None
    with pytest.raises(InvalidGameImageError, match="128"):
        parse_disc_header(b"\x00" * 10, format_name="ISO")
    crap = disc_header("CRAPPY", "Nope")
    with pytest.raises(InvalidGameIDError):
        parse_disc_header(crap, format_name="ISO")
    binary = bytearray(disc_header("RMCE01", "Title"))
    binary[0] = 0xFF
    with pytest.raises(InvalidGameImageError, match="ASCII"):
        parse_disc_header(bytes(binary), format_name="ISO")
    wbfs = tmp_path / "not.wbfs"
    wbfs.write_bytes(b"ISO9" + b"\x00" * 12)
    with pytest.raises(InvalidGameImageError, match="WBFS magic"):
        read_wbfs(wbfs)
    with pytest.raises(InvalidGameImageError, match="not a file"):
        read_image(tmp_path)
    folder = tmp_path / "Game [CRAPPY]"
    folder.mkdir()
    broken = folder / "CRAPPY.wbfs"
    broken.write_bytes(b"nope")
    with pytest.raises(InvalidGameIDError, match="Unable to determine"):
        detect_game(broken)

    class Short:
        def seek(self, *_args: object, **_kwargs: object) -> None:
            return None

        def tell(self) -> int:
            return 100

        def read(self, _size: int) -> bytes:
            return b"x"

        def __enter__(self) -> Short:
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: Short())
    with pytest.raises(InvalidGameImageError, match="Short read"):
        read_bounded(tmp_path / "x.bin", 0, 4)
    monkeypatch.undo()

    def denied(*_args: object, **_kwargs: object) -> object:
        raise OSError("denied")

    target = write_iso(tmp_path / "ok.iso", "RMCE01", "Mario")
    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(InvalidGameImageError, match="Cannot read"):
        read_image(target)


def test_library_scan_skips_links_and_paths_outside_the_root(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = isolated / "library"
    root.mkdir()
    write_wbfs(root / "inside.wbfs", "RMCE01", "Inside")
    write_iso(root / "nested" / "galaxy.iso", "RMGE01", "Galaxy")
    (root / "notes.txt").write_text("skip", encoding="utf-8")
    (root / "link.wbfs").symlink_to(root / "inside.wbfs")
    (root / "loop").symlink_to(root)
    write_wbfs(root / "escape.wbfs", "RSBE01", "Outside")
    real_resolve = Path.resolve

    def resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self.name == "escape.wbfs":
            return Path("/var/empty/escape.wbfs")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    found = [path.name for path in scan_library(root)]
    assert found == ["inside.wbfs", "galaxy.iso"]
    with pytest.raises(InvalidOptionError, match="not a directory"):
        scan_library(root / "inside.wbfs")


def test_batch_preflight_and_build(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_resolve(monkeypatch)
    root = isolated / "library"
    write_wbfs(root / "Mario Kart Wii [RMCE01]" / "RMCE01.wbfs", "RMCE01", "Mario Kart Wii")
    write_iso(root / "galaxy.iso", "RMGE01", "Super Mario Galaxy")
    output = isolated / "wad"
    output.mkdir()
    existing = output / output_filename("Mario Kart Wii", "RMCE01")
    existing.write_bytes(b"keep")
    with pytest.raises(OutputExistsError):
        plan_batch(root, output, loader="usbloadergx", source="usb")
    assert existing.read_bytes() == b"keep"
    existing.unlink()
    with pytest.raises(UnsupportedLoaderError):
        run_batch(root, output, loader="wiiflow")
    with pytest.raises(InvalidOptionError):
        _check_ios(True, True)  # type: ignore[arg-type]
    with pytest.raises(InvalidOptionError, match="3-255"):
        _check_ios(1, True)
    planned = plan_batch(root, output, loader="usbloadergx", source="usb")
    assert "Found 2 games." in format_dry_run(planned)
    assert "Would create 2 WAD files." in format_dry_run(planned)
    assert not any(output.iterdir())
    built = run_batch(root, output, source="sd", write_manifest=True)
    assert len(built) == 2
    summary = format_batch(built, output)
    assert "2/2 channels generated successfully." in summary
    assert "Mario Kart Wii" in summary
    assert Path(str(built[0].output) + ".json").is_file()
    assert validate_file(built[0].output).source == "sd"
    assert output_filename(" \n\t ", "RMCE01") == "RMCE01 [RMCE01].wad"
    assert explicit_game_id(None) is None
    assert explicit_game_id("rmce01") == "RMCE01"
    assert "Found 0 games." in format_dry_run([])


def test_create_writes_a_manifest_and_rejects_a_bad_banner(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_resolve(monkeypatch)
    image = write_iso(isolated / "game.iso", "RMCE01", "Mario Kart Wii")
    banner = isolated / "opening.bnr"
    banner.write_bytes(build_static_banner("Placeholder"))
    notes: list[str] = []
    result = create_shortcut(
        image,
        channel_id="abcd",
        source="sd",
        output=isolated / "out.wad",
        banner=banner,
        write_manifest=True,
        log=notes.append,
    )
    assert result.channel_id == "ABCD"
    assert result.source == "sd"
    sidecar = json.loads(Path(str(result.output) + ".json").read_text(encoding="utf-8"))
    assert sidecar["channel_id"] == "ABCD"
    assert sidecar["forwarder_sha256"] == "cd" * 32
    assert sidecar["tool"] == "wiishortcut"
    assert "title key" not in " ".join(notes)
    assert any("banner template user" in note for note in notes)
    text = format_create(result)
    assert "ABCD" in text
    assert "SD" in text
    game = detect_game(image)
    inspected = format_inspect(game, source="usb", verbose=True)
    assert "Disc number: 0" in inspected
    assert "ID source:" in inspected
    quiet = format_inspect(
        GameMetadata("RMCE01", "Title", None, "ISO", "override"),
        source="sd",
        verbose=False,
    )
    assert "Region: Unknown" in quiet
    assert "Disc number" not in quiet
    with pytest.raises(UnsupportedLoaderError):
        create_shortcut(image, loader="wiiflow", output=isolated / "no.wad")
    with pytest.raises(InvalidOptionError, match="integer"):
        create_shortcut(
            image,
            ios=True,  # type: ignore[arg-type]
            advanced=True,
            output=isolated / "no.wad",
        )
    with pytest.raises(InvalidWadError, match="not a file"):
        create_shortcut(image, banner=isolated / "missing.bnr", output=isolated / "no.wad")
    huge = isolated / "huge.bnr"
    with huge.open("wb") as handle:
        handle.seek(16)
        handle.write(b"x")
    monkeypatch.setattr("wiishortcut.pipeline.MAX_SECTION_BYTES", 8)
    with pytest.raises(InvalidWadError, match="over"):
        create_shortcut(image, banner=huge, output=isolated / "no.wad")
    with pytest.raises(InvalidWadError, match="not a file"):
        create_shortcut(image, base_wad=isolated / "missing.wad", output=isolated / "no.wad")
    with pytest.raises(InvalidWadError, match="not a file"):
        validate_file(isolated / "missing.wad")
    monkeypatch.setattr("wiishortcut.pipeline.MAX_WAD_BYTES", 4)
    small = isolated / "small.wad"
    small.write_bytes(b"12345")
    with pytest.raises(InvalidWadError, match="32 MiB"):
        validate_file(small)


def test_config_paths_keys_and_disagreement(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = isolated / "custom.toml"
    custom.write_text('default_source = "sd"\ndefault_ios = 58\n', encoding="utf-8")
    monkeypatch.setenv("WIISHORTCUT_CONFIG", str(custom))
    loaded = load_config()
    assert loaded.source == "sd"
    assert loaded.config_path == custom
    assert application_support_dir() == custom.parent
    monkeypatch.setenv("WIISHORTCUT_CACHE_DIR", str(isolated / "cache"))
    assert cache_dir() == isolated / "cache"
    monkeypatch.delenv("WIISHORTCUT_CONFIG")
    monkeypatch.delenv("WIISHORTCUT_CACHE_DIR")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated / "xdg"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(isolated / "xcache"))
    assert application_support_dir() == isolated / "xdg" / "wiishortcut"
    assert cache_dir() == isolated / "xcache" / "wiishortcut"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.delenv("XDG_CACHE_HOME")
    home = isolated / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert application_support_dir() == home / ".config" / "wiishortcut"
    assert cache_dir() == home / ".cache" / "wiishortcut"
    assert _bytes_equal(b"ab", b"abc") is False
    assert _bytes_equal(b"ab", b"ab") is True

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("WIISHORTCUT_CONFIG", str(isolated / "config"))
    monkeypatch.setenv("WII_COMMON_KEY_HEX", "ab" * 16)
    assert key_status() == "mismatch"
    with pytest.raises(MissingKeyError) as caught:
        from wiishortcut.config import assert_common_key

        assert_common_key()
    assert "ab" * 16 not in str(caught.value)
    keys = isolated / "config" / "keys.toml"
    keys.write_text('common_key_hex = "' + ("bb" * 16) + '"\n', encoding="utf-8")
    with pytest.raises(MissingKeyError, match="do not contain the same"):
        _supplied_key()
    monkeypatch.delenv("WII_COMMON_KEY_HEX")
    other = home / ".config" / "wiishortcut"
    other.mkdir(parents=True)
    (other / "keys.toml").write_text('common_key_hex = "' + ("11" * 16) + '"\n', encoding="utf-8")
    with pytest.raises(MissingKeyError, match="do not match each other"):
        _key_from_files()
    keys.write_text("[\n", encoding="utf-8")
    (other / "keys.toml").unlink()
    with pytest.raises(ConfigError, match="Cannot read"):
        _key_from_files()
    keys.write_text("common_key_hex = 5\n", encoding="utf-8")
    with pytest.raises(MissingKeyError, match="string"):
        _key_from_files()
    monkeypatch.setattr("wiishortcut.config.tomllib.loads", lambda _text: [1])
    keys.write_text('common_key_hex = "aa"\n', encoding="utf-8")
    assert _key_from_files() is None
    config = isolated / "config" / "config.toml"
    config.write_text("default_ios = 58\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="TOML table"):
        load_config()


def test_config_file_read_errors_are_config_errors(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = isolated / "config" / "config.toml"
    config.write_text("default_ios = 58\n", encoding="utf-8")
    real = Path.read_text

    def boom(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "config.toml":
            raise OSError("denied")
        return real(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", boom)
        with pytest.raises(ConfigError, match="Cannot read"):
            load_config()
    keys = isolated / "config" / "keys.toml"
    keys.write_text('common_key_hex = "aa"\n', encoding="utf-8")

    def boom_keys(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "keys.toml":
            raise OSError("denied")
        return real(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", boom_keys)
        with pytest.raises(ConfigError, match="Cannot read"):
            _key_from_files()


def test_assets_install_verify_and_reject(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsupportedLoaderError):
        asset_for("wiiflow", "usb")
    with pytest.raises(UnsupportedSourceError):
        asset_for("usbloadergx", "disc")
    monkeypatch.setattr("wiishortcut.forwarder.assets.load_manifest", lambda: {})
    with pytest.raises(AssetIntegrityError, match="one bootable"):
        asset_for("usbloadergx", "usb")
    data = synthetic_dol()
    usb = _asset(data)
    extra = _asset(data + b"x", filename="USBLoaderGXForwarder-copy.dol")
    monkeypatch.setattr(
        "wiishortcut.forwarder.assets.load_manifest",
        lambda: {"a": usb, "b": extra},
    )
    with pytest.raises(AssetIntegrityError, match="one bootable"):
        asset_for("usbloadergx", "usb")
    note = _asset(b"note", filename="note.bin", bootable=False)
    monkeypatch.setattr(
        "wiishortcut.forwarder.assets.load_manifest",
        lambda: {"forwarder-usb": usb, "note": note},
    )
    source = isolated / "in.dol"
    source.write_bytes(data)
    installed = install_asset(source, isolated / "assets")
    assert installed.sha256 == usb.sha256
    assert (isolated / "assets" / usb.filename).stat().st_mode & 0o777 == 0o644
    rows = {asset.filename: status for asset, status in verify_installed(isolated / "assets")}
    assert rows[usb.filename] == "ok"
    assert rows["note.bin"] == "not-bootable"
    blob, digest = resolve_forwarder(
        loader="usbloadergx",
        source="usb",
        assets_dir=isolated / "assets",
        explicit=source,
    )
    assert blob == data
    assert digest == usb.sha256
    (isolated / "assets" / usb.filename).write_bytes(b"changed")
    again = {asset.filename: status for asset, status in verify_installed(isolated / "assets")}
    assert again[usb.filename] == "mismatch"
    with pytest.raises(AssetIntegrityError, match="does not match"):
        resolve_forwarder(
            loader="usbloadergx",
            source="usb",
            assets_dir=isolated / "assets",
        )
    with pytest.raises(AssetIntegrityError, match="not a file"):
        resolve_forwarder(
            loader="usbloadergx",
            source="usb",
            assets_dir=isolated / "assets",
            explicit=isolated / "missing.dol",
        )

    def replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("full")

    monkeypatch.setattr(os, "replace", replace)
    source.write_bytes(data)
    with pytest.raises(OSError, match="full"):
        install_asset(source, isolated / "assets")
    assert not list((isolated / "assets").glob("*.tmp"))


def test_unreadable_forwarder_is_an_asset_error(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = isolated / "blocked.dol"
    path.write_bytes(synthetic_dol())
    real = Path.read_bytes

    def boom(self: Path) -> bytes:
        if self.name == "blocked.dol":
            raise OSError("denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(AssetIntegrityError, match="Cannot read"):
        resolve_forwarder(
            loader="usbloadergx",
            source="usb",
            assets_dir=isolated / "assets",
            explicit=path,
        )


def test_cli_json_batch_doctor_and_errors(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_resolve(monkeypatch)
    image = write_wbfs(isolated / "games" / "kart.wbfs", "RMCE01", "Mario Kart Wii")
    write_iso(isolated / "games" / "galaxy.iso", "RMGE01", "Super Mario Galaxy")
    created = runner.invoke(
        app,
        ["create", str(image), "--json", "--source", "sd", "--manifest", "--channel-id", "ABCD"],
    )
    assert created.exit_code == 0, created.stderr
    payload = json.loads(created.stdout)
    wad = Path(payload["output"])
    checked = runner.invoke(app, ["validate", str(wad), "--json"])
    assert checked.exit_code == 0
    body = json.loads(checked.stdout)
    assert body["status"] == "valid"
    assert body["channel_id"] == "ABCD"
    assert body["source"] == "sd"
    assert Path(str(wad) + ".json").is_file()
    inspected = runner.invoke(app, ["wad", "inspect", str(wad), "--json"])
    assert inspected.exit_code == 0
    assert json.loads(inspected.stdout)["channel_id"] == "ABCD"
    missing = runner.invoke(app, ["wad", "inspect", str(isolated / "missing.wad")])
    assert missing.exit_code == 4
    bad = isolated / "bad.wad"
    bad.write_bytes(b"nope")
    invalid = runner.invoke(app, ["validate", str(bad), "--json"])
    assert invalid.exit_code == 4
    assert json.loads(invalid.stdout)["ok"] is False
    dry = runner.invoke(
        app,
        [
            "batch",
            str(isolated / "games"),
            "--output",
            str(isolated / "out"),
            "--dry-run",
            "--json",
        ],
    )
    assert dry.exit_code == 0
    dry_body = json.loads(dry.stdout)
    assert dry_body["status"] == "dry-run"
    assert dry_body["count"] == 2
    assert not (isolated / "out").exists()
    built = runner.invoke(
        app,
        ["batch", str(isolated / "games"), "--output", str(isolated / "out"), "--json"],
    )
    assert built.exit_code == 0, built.stderr
    assert json.loads(built.stdout)["count"] == 2
    human = runner.invoke(
        app,
        ["batch", str(isolated / "games"), "--output", str(isolated / "again")],
    )
    assert human.exit_code == 0, human.stderr
    assert "2/2 channels generated successfully." in human.stdout
    refused = runner.invoke(
        app,
        ["create", str(image), "--loader", "wiiflow", "--output", str(isolated / "x.wad")],
    )
    assert refused.exit_code == 2
    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 0
    assert "Platform" in doctor.stdout
    assert "USB GX forwarder" in doctor.stdout
    assert "MISSING" in doctor.stdout


def test_cli_doctor_flags_and_unexpected_errors(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("importlib.metadata.version", missing)
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert "libWiiPy unknown" in version.stdout
    monkeypatch.setattr("wiishortcut.cli._rosetta", lambda: True)
    monkeypatch.setattr("wiishortcut.cli._output_writable", lambda: False)
    report = json.loads(runner.invoke(app, ["doctor", "--json"]).stdout)
    assert report["ok"] is False
    assert report["rosetta"] is True
    assert report["output_access"] == "fail"
    assert report["libwiipy"] == "unknown"
    (isolated / "config" / "config.toml").write_text("[\n", encoding="utf-8")
    broken = json.loads(runner.invoke(app, ["doctor", "--json"]).stdout)
    assert broken["assets"] == "missing"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("wiishortcut.cli.inspect_game", boom)
    image = write_iso(isolated / "game.iso", "RMCE01", "Mario")
    plain = runner.invoke(app, ["inspect", str(image)])
    assert plain.exit_code == 1
    assert "Unexpected failure" in plain.stderr
    assert "Traceback" not in plain.stderr
    debug = runner.invoke(app, ["--debug", "inspect", str(image), "--json"])
    assert debug.exit_code == 1
    assert "Traceback" in debug.stderr
    assert json.loads(debug.stdout)["exit_code"] == 1


def test_cli_installs_a_hash_matched_forwarder(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = synthetic_dol()
    usb = _asset(data)
    sd = _asset(synthetic_dol("sd"), device="sd", filename="USBLoaderGXForwarderSD.dol")
    monkeypatch.setattr(
        "wiishortcut.forwarder.assets.load_manifest",
        lambda: {"usb": usb, "sd": sd},
    )
    source = isolated / "USBLoaderGXForwarder.dol"
    source.write_bytes(data)
    installed = runner.invoke(app, ["assets", "install", str(source)])
    assert installed.exit_code == 0, installed.stderr
    assert "Installed" in installed.stdout
    source_sd = isolated / "sd.dol"
    source_sd.write_bytes(synthetic_dol("sd"))
    assert runner.invoke(app, ["assets", "install", str(source_sd)]).exit_code == 0
    verified = runner.invoke(app, ["assets", "verify"])
    assert verified.exit_code == 0
    assert "ok" in verified.stdout
    (isolated / "config" / "assets" / "USBLoaderGXForwarder.dol").write_bytes(b"nope")
    failed = runner.invoke(app, ["assets", "verify"])
    assert failed.exit_code == 3
    assert "mismatch" in failed.stdout


def test_platform_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert _rosetta() is False
    monkeypatch.setattr(sys, "platform", "darwin")

    def denied(*_args: object, **_kwargs: object) -> object:
        raise OSError("no sysctl")

    monkeypatch.setattr(subprocess, "run", denied)
    assert _rosetta() is None

    def answer(text: str):
        def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(stdout=text)

        return run

    monkeypatch.setattr(subprocess, "run", answer("1\n"))
    assert _rosetta() is True
    monkeypatch.setattr(subprocess, "run", answer("0\n"))
    assert _rosetta() is False
    monkeypatch.setattr(subprocess, "run", answer("maybe\n"))
    assert _rosetta() is None

    def unwritable(**_kwargs: object) -> object:
        raise OSError("read only")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", unwritable)
    assert _output_writable() is False
