"""Show DOL section tables and the byte ranges that differ.

Usage: python tools/dol_diff.py A.dol B.dol
"""

from __future__ import annotations

import sys
from pathlib import Path

from wiishortcut.wad.dol import parse_dol
from wiishortcut.wad.limits import MAX_DOL_BYTES

_LIMIT = MAX_DOL_BYTES


def _ranges(left: bytes, right: bytes) -> list[tuple[int, int]]:
    limit = min(len(left), len(right))
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index in range(limit):
        if left[index] != right[index]:
            if start is None:
                start = index
        elif start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, limit))
    if len(left) != len(right):
        ranges.append((limit, max(len(left), len(right))))
    return ranges


def _show(label: str, data: bytes) -> None:
    print(f"{label}  {len(data)} bytes")
    try:
        info = parse_dol(data)
    except Exception as exc:
        print(f"  parse: {exc}")
        return
    print(f"  entry {info.entry:#x}  bss {info.bss_address:#x}  bss-size {info.bss_size:#x}")
    for section in info.sections:
        print(
            f"  {section.kind:<4}  file {section.offset:#x}  "
            f"addr {section.address:#x}  size {section.size:#x}"
        )


def _read(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SystemExit(f"Cannot read {path.name}: {exc}") from exc
    if size > _LIMIT:
        raise SystemExit(f"{path.name} is over 8 MiB")
    return path.read_bytes()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python tools/dol_diff.py A.dol B.dol", file=sys.stderr)
        return 2
    left = _read(Path(argv[1]))
    right = _read(Path(argv[2]))
    _show("A", left)
    _show("B", right)
    print("changed ranges:")
    ranges = _ranges(left, right)
    if not ranges:
        print("  unchanged")
        return 0
    for start, end in ranges[:32]:
        preview = left[start : min(end, start + 8)]
        print(f"  {start:#x}-{end:#x}  {end - start} bytes  a[:8]={preview.hex()}")
    if len(ranges) > 32:
        print(f"  ... {len(ranges) - 32} more ranges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
