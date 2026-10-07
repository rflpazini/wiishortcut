"""Read only the Wii disc header from an ISO."""

import os
from pathlib import Path

from wiishortcut.errors import InvalidGameIDError, InvalidGameImageError
from wiishortcut.game.id import normalize_game_id
from wiishortcut.game.metadata import GameMetadata, region_from_game_id

DISC_MAGIC = 0x5D1C9EA3
HEADER_BYTES = 0x80
MAX_READ = 0x100


def read_bounded(path: Path, offset: int, size: int, *, limit: int = MAX_READ) -> bytes:
    """Read exactly `size` bytes at `offset`. Never read past EOF or `limit`."""
    if offset < 0 or size < 0:
        raise InvalidGameImageError(f"{path} has a negative read range.")
    if size > limit or offset > limit or offset + size > limit:
        raise InvalidGameImageError(
            f"Refusing to read {size} bytes at {offset} from {path.name}. "
            "Game identification only needs the disc header."
        )
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        length = handle.tell()
        if offset + size > length:
            raise InvalidGameImageError(
                f"{path.name} is {length} bytes. The disc header needs {offset + size} bytes."
            )
        handle.seek(offset)
        data = handle.read(size)
    if len(data) != size:
        raise InvalidGameImageError(f"Short read from {path.name}.")
    return data


def parse_disc_header(
    header: bytes,
    *,
    format_name: str,
    path: Path | None = None,
    require_game_id: bool = True,
) -> GameMetadata:
    """Parse a 0x80-byte Wii disc header into game metadata."""
    if len(header) < HEADER_BYTES:
        raise InvalidGameImageError("Disc header is shorter than 128 bytes.")
    magic = int.from_bytes(header[0x18:0x1C], "big")
    if magic != DISC_MAGIC:
        where = path.name if path is not None else format_name
        raise InvalidGameImageError(
            f"{where} does not contain a Wii disc header. "
            f"Expected magic 0x{DISC_MAGIC:08X} at offset 0x18 of the header."
        )
    try:
        raw_id = header[0:6].decode("ascii")
    except UnicodeDecodeError as exc:
        raise InvalidGameImageError("The disc header game ID is not ASCII.") from exc
    try:
        game_id = normalize_game_id(raw_id)
    except InvalidGameIDError:
        if require_game_id:
            raise
        game_id = ""
    raw_title = header[0x20:0x60].split(b"\x00", 1)[0]
    try:
        title = raw_title.decode("latin-1").strip()
    except UnicodeDecodeError as exc:
        raise InvalidGameImageError("The disc title is not latin-1.") from exc
    title = "".join(ch for ch in title if ch.isprintable()).strip()
    return GameMetadata(
        game_id=game_id,
        title=title,
        region=region_from_game_id(game_id),
        format=format_name,
        id_source=f"{format_name.lower()}-header",
        disc_number=header[6],
        disc_version=header[7],
        path=str(path) if path is not None else None,
    )


def read_iso(path: Path, *, require_game_id: bool = True) -> GameMetadata:
    """Read the game ID and title from the start of a Wii ISO."""
    header = read_bounded(path, 0, HEADER_BYTES)
    return parse_disc_header(
        header,
        format_name="ISO",
        path=path,
        require_game_id=require_game_id,
    )
