"""Read only the Wii disc header out of a single-game WBFS file.

USB Loader GX `.wbfs` files start with a WBFS header. Byte 8 is the hard-drive
sector size as a power of two. The Wii disc header, including the game ID,
lives at the start of the next sector. Identification never reads the game.
"""

from pathlib import Path

from wiishortcut.errors import InvalidGameImageError
from wiishortcut.game.iso import HEADER_BYTES, parse_disc_header, read_bounded
from wiishortcut.game.metadata import GameMetadata

WBFS_MAGIC = b"WBFS"
# 2**9 = 512 bytes, 2**15 = 32 KiB. Anything else is not a WBFS file we accept.
MIN_SECTOR_SHIFT = 9
MAX_SECTOR_SHIFT = 15


def read_wbfs(path: Path, *, require_game_id: bool = True) -> GameMetadata:
    """Read the game ID and title from a `.wbfs` file."""
    prefix = read_bounded(path, 0, 16, limit=16)
    if prefix[:4] != WBFS_MAGIC:
        raise InvalidGameImageError(
            f"{path.name} does not start with the WBFS magic. "
            "This reader expects a single-game .wbfs file."
        )
    sector_shift = prefix[8]
    if not MIN_SECTOR_SHIFT <= sector_shift <= MAX_SECTOR_SHIFT:
        raise InvalidGameImageError(
            f"{path.name} has WBFS sector shift {sector_shift}. "
            f"Expected a value from {MIN_SECTOR_SHIFT} to {MAX_SECTOR_SHIFT}."
        )
    sector = 1 << sector_shift
    header = read_bounded(path, sector, HEADER_BYTES, limit=sector + HEADER_BYTES)
    return parse_disc_header(
        header,
        format_name="WBFS",
        path=path,
        require_game_id=require_game_id,
    )
