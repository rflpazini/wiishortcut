"""Build a structural channel banner and rewrite its IMET name.

The banner is content 0 of the channel. It is an IMET header followed by a U8
archive of icon.bin, banner.bin, and sound.bin. Each of those files starts
with an IMD5 header.

The built-in payloads are a marked static template. They make the WAD
structurally valid and keep the System Menu from receiving an arbitrary game
banner. They are not a Dolphin-certified animation. Pass `--banner` with a
banner you already trust when you need a channel you will install.
"""

import hashlib
import tempfile
from pathlib import Path

from libWiiPy.archive.u8 import IMETHeader, U8Archive, pack_u8

from wiishortcut.errors import InvalidWadError
from wiishortcut.game.id import normalize_channel_name

BANNER_MARKER = b"WIISHORTCUT-BANNER-V1"
ICON_MARKER = b"WIISHORTCUT-ICON-V1"
MAX_BANNER_BYTES = 8 * 1024 * 1024
IMET_MAGIC = b"IMET"
U8_MAGIC = b"\x55\xaa\x38\x2d"


def imd5_wrap(payload: bytes) -> bytes:
    """Prefix `payload` with a 32-byte IMD5 header."""
    if len(payload) > MAX_BANNER_BYTES:
        raise InvalidWadError("Banner component is larger than 8 MiB.")
    digest = hashlib.md5(payload).digest()
    header = b"IMD5" + len(payload).to_bytes(4, "big") + (b"\x00" * 8) + digest
    return header + payload


def build_static_banner(name: str) -> bytes:
    """Return a 00000000.app image whose IMET name is `name` in every language."""
    cleaned = normalize_channel_name(name)
    with tempfile.TemporaryDirectory(prefix="wiishortcut-banner-") as temporary:
        root = Path(temporary)
        icon = imd5_wrap(ICON_MARKER)
        banner = imd5_wrap(BANNER_MARKER)
        sound = imd5_wrap(b"\x00\x00")
        (root / "icon.bin").write_bytes(icon)
        (root / "banner.bin").write_bytes(banner)
        (root / "sound.bin").write_bytes(sound)
        archive = pack_u8(root)
        sizes = [len(icon), len(banner), len(sound)]
    header = IMETHeader()
    header.create(sizes, [(index, cleaned) for index in range(10)])
    packed = header.dump() + archive
    if packed[0x40:0x44] != IMET_MAGIC:
        raise InvalidWadError("Generated banner is missing the IMET magic.")
    if packed[0x600:0x604] != U8_MAGIC:
        raise InvalidWadError("Generated banner is missing the U8 archive.")
    return packed


def safe_u8_name(name: str) -> bool:
    """Reject a U8 node name that is absolute, empty-dot, or walks upward."""
    if name.startswith(("/", "\\")) or "\x00" in name:
        return False
    parts = name.replace("\\", "/").split("/")
    return ".." not in parts and "." not in parts[1:]


def u8_offset(data: bytes) -> int:
    """Return the U8 magic offset. IMET puts it at 0x600, or 0x640 after a build tag."""
    if len(data) >= 0x604 and data[0x600:0x604] == U8_MAGIC:
        return 0x600
    if len(data) >= 0x644 and data[0x640:0x644] == U8_MAGIC:
        return 0x640
    raise InvalidWadError("Banner U8 archive is not valid.")


def u8_entry_names(data: bytes, offset: int) -> list[str]:
    """Read node names. A node count or a string that does not fit is an error."""
    blob = data[offset:]
    if len(blob) < 0x2C:
        raise InvalidWadError("Banner U8 node table does not fit.")
    count = int.from_bytes(blob[0x28:0x2C], "big")
    table_end = 0x20 + count * 12
    if count < 1 or table_end > len(blob):
        raise InvalidWadError("Banner U8 node table does not fit.")
    names: list[str] = []
    for index in range(count):
        node = 0x20 + index * 12
        name_off = int.from_bytes(blob[node + 1 : node + 4], "big")
        start = table_end + name_off
        if start >= len(blob):
            raise InvalidWadError("Banner U8 name is not NUL-terminated.")
        end = blob.find(b"\x00", start)
        if end < 0:
            raise InvalidWadError("Banner U8 name is not NUL-terminated.")
        try:
            names.append(blob[start:end].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise InvalidWadError("Banner U8 name is not UTF-8.") from exc
    return names


def assert_u8_entry_names(data: bytes) -> int:
    """Reject an unsafe U8 before libWiiPy walks its node table. Returns the offset."""
    offset = u8_offset(data)
    for name in u8_entry_names(data, offset):
        if name and not safe_u8_name(name):
            raise InvalidWadError("U8 entry name is not a relative path.")
    return offset


def retitle_banner(data: bytes, name: str) -> bytes:
    """Rewrite every IMET language and recompute the IMET MD5. The U8 is unchanged."""
    if len(data) < 0x600 or len(data) > MAX_BANNER_BYTES:
        raise InvalidWadError(
            f"Banner is {len(data)} bytes. Expected a file between {0x600} bytes and 8 MiB."
        )
    cleaned = normalize_channel_name(name)
    header_at = _imet_offset(data)
    header = IMETHeader()
    header.load(data[header_at : header_at + 0x600])
    if header.magic != "IMET":
        raise InvalidWadError("Banner IMET magic is not IMET.")
    header.set_channel_names([(index, cleaned) for index in range(10)])
    rewritten = header.dump()
    if len(rewritten) != 0x600:
        raise InvalidWadError("Rewritten IMET header is not 1536 bytes.")
    updated = data[:header_at] + rewritten + data[header_at + 0x600 :]
    offset = assert_u8_entry_names(updated)
    archive = U8Archive()
    try:
        archive.load(updated[offset:])
    except (TypeError, ValueError, UnicodeError) as exc:
        raise InvalidWadError(f"Banner U8 archive is not valid: {exc}") from exc
    return updated


def imet_md5_matches(banner: bytes) -> bool:
    """Recompute the IMET MD5 the way libWiiPy writes it and compare."""
    header_at = _imet_offset(banner)
    header = banner[header_at : header_at + 0x600]
    if len(header) != 0x600 or header[0x40:0x44] != IMET_MAGIC:
        return False
    digest_at = 0x600 - 16
    recomputed = hashlib.md5(header[:digest_at] + (b"\x00" * 16)).digest()
    return header[digest_at:] == recomputed


def _imet_offset(data: bytes) -> int:
    if len(data) >= 0x44 and data[0x40:0x44] == IMET_MAGIC:
        return 0
    if len(data) >= 0x84 and data[0x80:0x84] == IMET_MAGIC:
        return 0x40
    raise InvalidWadError("Banner has no IMET header at offset 0x40 or 0x80.")
