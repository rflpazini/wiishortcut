"""Synthetic images and forwarders. These bytes are not Nintendo content."""

from __future__ import annotations

import struct
from pathlib import Path

from wiishortcut.game.iso import DISC_MAGIC

_PATHS = b"apps/usbloader_gx/boot.dol\x00apps/usbloadergx/boot.dol\x00"


def disc_header(game_id: str, title: str, *, disc: int = 0, version: int = 0) -> bytes:
    header = bytearray(0x80)
    header[0:6] = game_id.encode("ascii")
    header[6] = disc
    header[7] = version
    header[0x18:0x1C] = struct.pack(">I", DISC_MAGIC)
    encoded = title.encode("latin-1")[:64]
    header[0x20 : 0x20 + len(encoded)] = encoded
    return bytes(header)


def write_iso(path: Path, game_id: str, title: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(disc_header(game_id, title))
    return path


def write_wbfs(path: Path, game_id: str, title: str, *, sector_shift: int = 9) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sector = 1 << sector_shift
    blob = bytearray(sector + 0x80)
    blob[0:4] = b"WBFS"
    blob[8] = sector_shift
    blob[sector : sector + 0x80] = disc_header(game_id, title)
    path.write_bytes(blob)
    return path


def synthetic_dol(source: str = "usb") -> bytes:
    """A DOL with the WiiGSC 1.1 USB Loader GX slot layout, and no Nintendo code."""
    payload = bytearray(b"CFGUGX")
    payload.extend(b"\x00" * (144 - len(payload)))
    payload.extend(b"CRAPPY")
    payload.extend(b"\x00\x00")
    payload.extend(b"TCRP")
    payload.extend(b"\x00\x00\x00\x00")
    payload.extend(b"UGXWVC")
    payload.extend(b"\x00")
    payload.extend(_PATHS)
    if source == "sd":
        payload.extend(b"--sdmode=1\x00")
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0x1C, 0x100)
    struct.pack_into(">I", header, 0x64, 0x80004000)
    struct.pack_into(">I", header, 0xAC, len(payload))
    struct.pack_into(">I", header, 0xE0, 0x80004000)
    return bytes(header) + bytes(payload)
