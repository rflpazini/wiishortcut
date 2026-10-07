"""Pack a WAD, read it back, and refuse hostile headers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.support import synthetic_dol

from wiishortcut.align import align, pad
from wiishortcut.channel.banner import build_static_banner
from wiishortcut.errors import InvalidWadError, OutputExistsError
from wiishortcut.forwarder.usbloadergx import patch_usbloadergx, read_patched_game_id
from wiishortcut.pipeline import atomic_write_wad
from wiishortcut.wad.builder import build_wad, derive_title_key
from wiishortcut.wad.dol import parse_dol
from wiishortcut.wad.validator import describe_wad, format_report, validate_wad

BASE = Path("/tmp/wiishortcut-research/release/NandLoaders/universal-base.wxd")


def _wad(ios: int = 58, game_id: str = "RMCE01", channel_id: str = "UMCE") -> bytes:
    dol = patch_usbloadergx(synthetic_dol("usb"), game_id, "usb")
    banner = build_static_banner("Mario Kart Wii")
    return build_wad(
        banner=banner,
        dol=dol,
        channel_id=channel_id,
        game_id=game_id,
        loader="usbloadergx",
        source="usb",
        ios=ios,
    )


def test_roundtrip_preserves_title_banner_and_game_id() -> None:
    first = _wad()
    second = _wad()
    assert first == second
    report = validate_wad(first)
    assert report.ok, format_report(report)
    assert report.game_id == "RMCE01"
    assert report.channel_id == "UMCE"
    assert report.ios == 58
    assert report.source == "usb"
    text = format_report(report)
    assert "VALID" in text
    assert "Game ID RMCE01" in text
    assert "structural, not System Menu certified" in text
    info = describe_wad(first)
    assert info["title_id"] == "00010001554d4345"
    assert info["banner_name"] == "Mario Kart Wii"
    assert info["boot_index"] == 1
    boot = next(item for item in info["contents"] if item["index"] == 1)
    dol = patch_usbloadergx(synthetic_dol("usb"), "RMCE01", "usb")
    assert read_patched_game_id(dol) == "RMCE01"
    assert boot["size"] == len(dol)


def test_source_date_epoch_changes_only_the_footer(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = _wad()
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    stamped = _wad()
    assert plain != stamped
    assert validate_wad(stamped).ok
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "nope")
    with pytest.raises(InvalidWadError):
        _wad()


def test_non_default_ios_is_a_warning_and_strict_fails_it() -> None:
    wad = _wad(ios=56)
    relaxed = validate_wad(wad, strict=False)
    assert relaxed.ok
    assert any(check.state == "WARN" and check.label == "IOS 56" for check in relaxed.checks)
    strict = validate_wad(wad, strict=True)
    assert not strict.ok
    assert "INVALID" in format_report(strict)


def test_title_key_is_deterministic_and_sixteen_bytes() -> None:
    key = derive_title_key(game_id="RMCE01", channel_id="UMCE", source="usb", loader="usbloadergx")
    assert key == derive_title_key(
        game_id="RMCE01", channel_id="UMCE", source="usb", loader="usbloadergx"
    )
    assert len(key) == 16
    assert key != derive_title_key(
        game_id="RSBE01", channel_id="USBE", source="usb", loader="usbloadergx"
    )


def test_base_wad_region_is_reset_to_world() -> None:
    from libWiiPy.title.title import Title

    base_title = Title()
    base_title.load_wad(_wad())
    base_title.tmd.region = 1
    base_title.fakesign()
    base = base_title.dump_wad()
    loaded = Title()
    loaded.load_wad(base)
    assert loaded.tmd.region == 1
    rebuilt = build_wad(
        banner=build_static_banner("Mario Kart Wii"),
        dol=patch_usbloadergx(synthetic_dol("usb"), "RMCE01", "usb"),
        channel_id="UMCE",
        game_id="RMCE01",
        loader="usbloadergx",
        source="usb",
        ios=58,
        base_wad=base,
    )
    result = Title()
    result.load_wad(rebuilt)
    assert result.tmd.region == 3


def test_non_world_region_fails_strict_validation() -> None:
    from libWiiPy.title.title import Title

    title = Title()
    title.load_wad(_wad())
    title.tmd.region = 1
    title.fakesign()
    data = title.dump_wad()
    relaxed = validate_wad(data)
    assert any(check.label == "Region" and check.state == "WARN" for check in relaxed.checks)
    assert relaxed.ok
    assert not validate_wad(data, strict=True).ok


def _ticket_offset(data: bytes) -> int:
    sizes = [int.from_bytes(data[0x08 + index * 4 : 0x0C + index * 4], "big") for index in range(6)]
    offset = 0x40
    for size in sizes[:2]:
        offset = (offset + size + 0x3F) & ~0x3F
    return offset


def test_base_wad_must_use_the_retail_common_key() -> None:
    retail = _wad()
    ticket_at = _ticket_offset(retail)
    korean = bytearray(retail)
    korean[ticket_at + 0x1F1] = 1
    banner = build_static_banner("Mario Kart Wii")
    dol = patch_usbloadergx(synthetic_dol("usb"), "RMCE01", "usb")
    with pytest.raises(InvalidWadError, match="retail common key"):
        build_wad(
            banner=banner,
            dol=dol,
            channel_id="UMCE",
            game_id="RMCE01",
            loader="usbloadergx",
            source="usb",
            ios=58,
            base_wad=bytes(korean),
        )
    dev = bytearray(retail)
    issuer_at = ticket_at + 0x140
    issuer = b"Root-CA00000002-XS00000006"
    dev[issuer_at : issuer_at + len(issuer)] = issuer
    with pytest.raises(InvalidWadError, match="retail common key"):
        build_wad(
            banner=banner,
            dol=dol,
            channel_id="UMCE",
            game_id="RMCE01",
            loader="usbloadergx",
            source="usb",
            ios=58,
            base_wad=bytes(dev),
        )
    vwii = bytearray(retail)
    vwii[ticket_at + 0x1F1] = 2
    with pytest.raises(InvalidWadError, match="retail common key"):
        build_wad(
            banner=banner,
            dol=dol,
            channel_id="UMCE",
            game_id="RMCE01",
            loader="usbloadergx",
            source="usb",
            ios=58,
            base_wad=bytes(vwii),
        )
    unknown = bytearray(retail)
    unknown[ticket_at + 0x1F1] = 224
    packed = build_wad(
        banner=banner,
        dol=dol,
        channel_id="UMCE",
        game_id="RMCE01",
        loader="usbloadergx",
        source="usb",
        ios=58,
        base_wad=bytes(unknown),
    )
    assert validate_wad(packed).ok


def test_publish_copies_when_the_filesystem_has_no_hard_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    from wiishortcut.fs import link_exclusive, write_temp

    temporary = write_temp(tmp_path, b"wad-bytes")
    destination = tmp_path / "game.wad"

    def no_link(_source: str, _destination: str) -> None:
        raise OSError(errno.ENOTSUP, "link")

    monkeypatch.setattr(os, "link", no_link)
    link_exclusive(temporary, destination)
    assert destination.read_bytes() == b"wad-bytes"
    with pytest.raises(OutputExistsError):
        link_exclusive(temporary, destination)
    assert destination.read_bytes() == b"wad-bytes"


def test_publish_copy_does_not_follow_a_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    from wiishortcut.fs import link_exclusive, write_temp

    game = tmp_path / "game.wbfs"
    game.write_bytes(b"GAME-BYTES")
    destination = tmp_path / "out.wad"
    destination.symlink_to(game)
    temporary = write_temp(tmp_path, b"wad-bytes")

    def no_link(*_args: object) -> None:
        raise OSError(errno.EPERM, "link")

    monkeypatch.setattr(os, "link", no_link)
    with pytest.raises(OutputExistsError):
        link_exclusive(temporary, destination)
    assert game.read_bytes() == b"GAME-BYTES"
    assert destination.is_symlink()


def test_publish_does_not_hide_an_io_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import errno

    from wiishortcut.fs import link_exclusive, write_temp

    temporary = write_temp(tmp_path, b"wad-bytes")
    destination = tmp_path / "game.wad"

    def io_error(*_args: object) -> None:
        raise OSError(errno.EIO, "io")

    monkeypatch.setattr(os, "link", io_error)
    with pytest.raises(OSError):
        link_exclusive(temporary, destination)
    assert not destination.exists()


def test_atomic_write_does_not_follow_a_tmp_symlink(tmp_path: Path) -> None:
    game = tmp_path / "game.wbfs"
    game.write_bytes(b"GAME-BYTES")
    destination = tmp_path / "out.wad"
    link = Path(str(destination) + ".tmp")
    link.symlink_to(game)
    report = atomic_write_wad(destination, _wad())
    assert report.ok
    assert game.read_bytes() == b"GAME-BYTES"
    assert destination.is_file()
    assert not destination.is_symlink()


def test_atomic_write_refuses_a_dangling_symlink(tmp_path: Path) -> None:
    destination = tmp_path / "out.wad"
    destination.symlink_to(tmp_path / "missing")
    with pytest.raises(OutputExistsError):
        atomic_write_wad(destination, _wad())
    assert destination.is_symlink()
    assert not destination.exists()


def _with_bad_content_hash(data: bytes) -> bytes:
    for offset in range(len(data) - 1, 0x40, -1):
        trial = bytearray(data)
        trial[offset] ^= 0xFF
        report = validate_wad(bytes(trial))
        if any(check.label == "SHA-1" and check.state == "FAIL" for check in report.checks):
            return bytes(trial)
    raise AssertionError("no content byte changed the SHA-1")


def test_describe_rejects_a_content_hash_failure() -> None:
    with pytest.raises(InvalidWadError):
        describe_wad(_with_bad_content_hash(_wad()))


def test_atomic_write_validates_from_disk_and_cleans_up(tmp_path: Path) -> None:
    destination = tmp_path / "Mario Kart Wii [RMCE01].wad"
    report = atomic_write_wad(destination, _wad())
    assert report.ok
    assert destination.is_file()
    assert not Path(str(destination) + ".tmp").exists()
    with pytest.raises(OutputExistsError):
        atomic_write_wad(destination, _wad())
    rejected = tmp_path / "bad.wad"
    with pytest.raises(InvalidWadError):
        atomic_write_wad(rejected, b"not a wad")
    assert not rejected.exists()
    assert not Path(str(rejected) + ".tmp").exists()


def test_malformed_header_does_not_raise_index_error() -> None:
    report = validate_wad(b"\x00" * 8)
    assert not report.ok
    huge = bytearray(b"\x00\x00\x00\x20Is\x00\x00")
    huge.extend((100_000_000).to_bytes(4, "big"))
    huge.extend(b"\x00" * 16)
    report = validate_wad(bytes(huge))
    assert not report.ok


def test_dol_parser_rejects_a_short_file() -> None:
    with pytest.raises(InvalidWadError):
        parse_dol(b"\x00" * 16)
    info = parse_dol(synthetic_dol())
    assert info.entry != 0
    assert info.sections


@given(st.integers(min_value=0, max_value=5000), st.integers(min_value=1, max_value=128))
def test_align_and_pad(value: int, boundary: int) -> None:
    aligned = align(value, boundary)
    assert aligned >= value
    assert aligned % boundary == 0
    padded = pad(b"x" * (value % 40), boundary)
    assert len(padded) % boundary == 0


def test_align_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        align(-1)
    with pytest.raises(ValueError):
        align(1, 0)
    with pytest.raises(TypeError):
        pad("nope")  # type: ignore[arg-type]


@given(st.binary(max_size=80))
def test_random_bytes_do_not_crash_the_parser(blob: bytes) -> None:
    try:
        report = validate_wad(blob)
    except InvalidWadError:
        return
    assert report.ok is False


@pytest.mark.skipif(not BASE.is_file(), reason="local universal-base.wxd is absent")
def test_user_base_wad_keeps_its_certificate_chain() -> None:
    base = BASE.read_bytes()
    wad = build_wad(
        banner=build_static_banner("Base Path"),
        dol=patch_usbloadergx(synthetic_dol(), "RMCE01", "usb"),
        channel_id="UMCE",
        game_id="RMCE01",
        loader="usbloadergx",
        source="usb",
        ios=58,
        base_wad=base,
    )
    report = validate_wad(wad)
    assert report.ok, format_report(report)
    assert report.channel_id == "UMCE"
    assert wad[8:12] == base[8:12]


def test_epoch_is_unset_for_the_plain_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    assert os.environ.get("SOURCE_DATE_EPOCH") in {None, ""}
    assert validate_wad(_wad()).ios == 58
