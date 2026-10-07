"""Show how two WAD files differ, without printing ticket or certificate bytes.

Usage: python tools/wad_diff.py A.wad B.wad
"""

from __future__ import annotations

import sys
from pathlib import Path

from libWiiPy.title.title import Title

_MAGIC = bytes.fromhex("0000002049730000")
_NAMES = ("cert", "crl", "ticket", "tmd", "content", "meta")
_LIMIT = 32 * 1024 * 1024


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def _load(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SystemExit(f"Cannot read {path.name}: {exc}") from exc
    if size > _LIMIT:
        raise SystemExit(f"{path.name} is over 32 MiB")
    return path.read_bytes()


def _sections(data: bytes) -> list[tuple[str, int, int]]:
    if len(data) < 0x40 or data[:8] != _MAGIC:
        return [("file", 0, len(data))]
    sizes = [_u32(data, 0x08 + index * 4) for index in range(6)]
    offset = 0x40
    found = [("header", 0, 0x40)]
    for name, size in zip(_NAMES, sizes, strict=True):
        end = offset + size
        if end > len(data):
            found.append((name, offset, max(0, len(data) - offset)))
            break
        found.append((name, offset, size))
        offset = (end + 0x3F) & ~0x3F
    return found


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


def _print_ranges(ranges: list[tuple[int, int]]) -> None:
    if not ranges:
        print("  unchanged")
        return
    for start, end in ranges[:32]:
        print(f"  {start:#x}-{end:#x}  {end - start} bytes")
    if len(ranges) > 32:
        print(f"  ... {len(ranges) - 32} more ranges")


def _describe(data: bytes) -> None:
    title = Title()
    try:
        title.load_wad(data)
    except (OSError, TypeError, ValueError, IndexError) as exc:
        print(f"  parse: {exc.__class__.__name__}")
        return
    print(f"  title-id {title.tmd.title_id}")
    print(f"  ios {title.tmd.ios_version}  boot {title.tmd.boot_index}")
    for record in title.tmd.content_records:
        digest = record.content_hash.decode(errors="replace")
        print(
            f"  content index {record.index}  id {record.content_id}  "
            f"size {record.content_size}  sha1 {digest}"
        )


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python tools/wad_diff.py A.wad B.wad", file=sys.stderr)
        return 2
    left_path, right_path = Path(argv[1]), Path(argv[2])
    left, right = _load(left_path), _load(right_path)
    print(f"A {left_path}  {len(left)} bytes")
    print(f"B {right_path}  {len(right)} bytes")
    print("A")
    _describe(left)
    print("B")
    _describe(right)
    right_sections = {name: (offset, size) for name, offset, size in _sections(right)}
    for name, offset, size in _sections(left):
        print(name.upper())
        other = right_sections.get(name)
        if other is None:
            print("  missing from B")
            continue
        if name in {"cert", "ticket"}:
            same = left[offset : offset + size] == right[other[0] : other[0] + other[1]]
            note = "identical" if same else f"differs ({size} vs {other[1]} bytes), bytes hidden"
            print(f"  {note}")
            continue
        chunk_a = left[offset : offset + size]
        chunk_b = right[other[0] : other[0] + other[1]]
        _print_ranges(_ranges(chunk_a, chunk_b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
