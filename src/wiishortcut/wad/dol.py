"""Parse a DOL header far enough to reject a truncated or overflowing file.

The System Menu boots content index 1. This parser does not emulate the DOL.
It checks the section table so a short or hostile file cannot pass as a
forwarder.
"""

from __future__ import annotations

from dataclasses import dataclass

from wiishortcut.errors import InvalidWadError
from wiishortcut.wad.limits import MAX_DOL_BYTES

_TEXT_SECTIONS = 7
_DATA_SECTIONS = 11


@dataclass(frozen=True)
class DolSection:
    """One text or data section from the DOL header."""

    kind: str
    offset: int
    address: int
    size: int


@dataclass(frozen=True)
class DolInfo:
    """The fields this project validates. BSS is recorded and not executed."""

    sections: tuple[DolSection, ...]
    bss_address: int
    bss_size: int
    entry: int


def parse_dol(data: bytes) -> DolInfo:
    """Parse a DOL. Raise ``InvalidWadError`` instead of reading past the file."""
    if len(data) < 0x100:
        raise InvalidWadError("DOL is shorter than the 256-byte header.")
    if len(data) > MAX_DOL_BYTES:
        raise InvalidWadError("DOL is larger than 8 MiB.")
    sections: list[DolSection] = []
    for index in range(_TEXT_SECTIONS):
        sections.append(_section(data, "text", index, 0x00, 0x48, 0x90))
    for index in range(_DATA_SECTIONS):
        sections.append(_section(data, "data", index, 0x1C, 0x64, 0xAC))
    present = tuple(section for section in sections if section.size > 0)
    if not present:
        raise InvalidWadError("DOL has no sections.")
    for section in present:
        if section.offset < 0x100:
            raise InvalidWadError(
                f"DOL {section.kind} section starts at {section.offset}, inside the header."
            )
        end = section.offset + section.size
        if section.size < 0 or end < section.offset or end > len(data):
            raise InvalidWadError(
                f"DOL {section.kind} section at {section.offset} does not fit in {len(data)} bytes."
            )
    bss_address = _u32(data, 0xD8)
    bss_size = _u32(data, 0xDC)
    entry = _u32(data, 0xE0)
    if entry == 0:
        raise InvalidWadError("DOL entry point is 0.")
    return DolInfo(
        sections=present,
        bss_address=bss_address,
        bss_size=bss_size,
        entry=entry,
    )


def _section(
    data: bytes,
    kind: str,
    index: int,
    offset_at: int,
    address_at: int,
    size_at: int,
) -> DolSection:
    return DolSection(
        kind=kind,
        offset=_u32(data, offset_at + index * 4),
        address=_u32(data, address_at + index * 4),
        size=_u32(data, size_at + index * 4),
    )


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")
