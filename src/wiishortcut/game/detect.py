"""Choose a game ID from the image, the path, or an explicit override."""

from pathlib import Path

from wiishortcut.errors import InvalidGameIDError, InvalidGameImageError
from wiishortcut.game.id import BRACKET_RE, normalize_game_id
from wiishortcut.game.iso import read_iso
from wiishortcut.game.metadata import GameMetadata, region_from_game_id
from wiishortcut.game.wbfs import read_wbfs


def game_id_from_path(path: Path) -> str | None:
    """Return a game ID from a `[GAMEID]` path component or the file stem."""
    for part in reversed(path.parts):
        match = BRACKET_RE.search(part)
        if match:
            return normalize_game_id(match.group(1))
    stem = path.stem.upper()
    if len(stem) == 6 and stem.isalnum():
        return normalize_game_id(stem)
    return None


def title_from_path(path: Path) -> str | None:
    """Use the parent folder name, without the `[GAMEID]` suffix, as a title."""
    parent = path.parent.name
    if not parent or parent in {".", "/", path.anchor}:
        return None
    cleaned = BRACKET_RE.sub("", parent)
    cleaned = " ".join(cleaned.split()).strip(" -_")
    return cleaned or None


def read_image(path: Path, *, require_game_id: bool = True) -> GameMetadata:
    """Detect ISO vs WBFS from the header, not from the file extension alone."""
    if not path.is_file():
        raise InvalidGameImageError(f"{path} is not a file.")
    try:
        with path.open("rb") as handle:
            prefix = handle.read(4)
    except OSError as exc:
        raise InvalidGameImageError(f"Cannot read {path}: {exc}") from exc
    if prefix == b"WBFS":
        return read_wbfs(path, require_game_id=require_game_id)
    return read_iso(path, require_game_id=require_game_id)


def detect_game(path: Path, *, game_id: str | None = None, name: str | None = None) -> GameMetadata:
    """Resolve metadata. An explicit game ID wins over the disc header."""
    explicit = normalize_game_id(game_id) if game_id else None
    image: GameMetadata | None = None
    image_error: InvalidGameImageError | None = None
    try:
        image = read_image(path)
    except InvalidGameImageError as exc:
        image_error = exc
    except InvalidGameIDError:
        image = read_image(path, require_game_id=False)

    if image is not None:
        chosen, id_source = _choose_id(explicit, image, path)
        title = name or image.title or title_from_path(path) or chosen
        return GameMetadata(
            game_id=chosen,
            title=title,
            region=region_from_game_id(chosen),
            format=image.format,
            id_source=id_source,
            disc_number=image.disc_number,
            disc_version=image.disc_version,
            path=str(path),
        )

    if explicit is not None:
        raise InvalidGameImageError(
            f"{image_error} The file must still be a readable Wii ISO or WBFS image."
        )

    raise InvalidGameIDError(_undetectable_message(readable=False))


def _choose_id(explicit: str | None, image: GameMetadata, path: Path) -> tuple[str, str]:
    """Pick explicit, then a usable header ID, then a bracket, then a filename."""
    if explicit:
        source = "override" if explicit != image.game_id else image.id_source
        return explicit, source
    if image.game_id:
        return image.game_id, image.id_source
    found = _id_from_path(path)
    if found is None:
        raise InvalidGameIDError(_undetectable_message(readable=True))
    return found


def _id_from_path(path: Path) -> tuple[str, str] | None:
    """Return a path ID that is safe to use when the disc header ID is not."""
    for part in reversed(path.parts):
        match = BRACKET_RE.search(part)
        if match is None:
            continue
        try:
            return normalize_game_id(match.group(1)), "path"
        except InvalidGameIDError:
            continue
    stem = path.stem.upper()
    if len(stem) == 6 and stem.isalnum():
        try:
            return normalize_game_id(stem), "filename"
        except InvalidGameIDError:
            return None
    return None


def _undetectable_message(*, readable: bool) -> str:
    detail = (
        "The disc header game ID is not a Wii game ID."
        if readable
        else "The file is not a readable Wii ISO or WBFS image."
    )
    return (
        "Unable to determine the Wii Game ID.\n\n"
        "Tried:\n"
        "  WBFS metadata\n"
        "  directory name\n"
        "  filename\n\n"
        f"{detail}"
    )
