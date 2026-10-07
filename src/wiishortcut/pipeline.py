"""Turn a game image into a validated WAD, or scan a library and do that in batch.

Nothing here writes the game, a NAND, or a USB Loader GX config. The WAD is
written to a temporary file, validated from that file, and renamed into place.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wiishortcut import __version__
from wiishortcut.channel.builder import assemble_channel
from wiishortcut.channel.title_id import channel_id_from_game_id, normalize_channel_id
from wiishortcut.config import AppConfig, assert_common_key, load_config
from wiishortcut.errors import (
    ChannelIdCollisionError,
    InvalidOptionError,
    InvalidWadError,
    OutputExistsError,
    UnsupportedLoaderError,
)
from wiishortcut.forwarder.assets import resolve_forwarder
from wiishortcut.forwarder.usbloadergx import patch_usbloadergx
from wiishortcut.fs import fsync_dir, link_exclusive, write_temp
from wiishortcut.game.detect import detect_game
from wiishortcut.game.id import normalize_game_id
from wiishortcut.game.metadata import GameMetadata
from wiishortcut.wad.builder import build_wad
from wiishortcut.wad.limits import MAX_SECTION_BYTES, MAX_WAD_BYTES
from wiishortcut.wad.validator import ValidationReport, format_report, validate_wad

Log = Callable[[str], None]


@dataclass(frozen=True)
class CreateResult:
    """What ``create`` returns after the WAD is on disk."""

    game: GameMetadata
    channel_id: str
    loader: str
    source: str
    ios: int
    output: Path
    wad_sha256: str
    forwarder_sha256: str


@dataclass(frozen=True)
class PlannedGame:
    """One batch row, computed before any WAD is written."""

    game: GameMetadata
    channel_id: str
    output: Path


def inspect_game(
    path: Path,
    *,
    game_id: str | None = None,
    name: str | None = None,
) -> GameMetadata:
    """Read only the disc header."""
    return detect_game(path, game_id=game_id, name=name)


def format_inspect(game: GameMetadata, *, source: str, verbose: bool = False) -> str:
    """Render ``inspect`` the way the CLI shows it."""
    region = game.region or "Unknown"
    lines = [
        f"Format: {game.format}",
        f"Game ID: {game.game_id}",
        f"Title: {game.title}",
        f"Region: {region}",
        f"Loader: {game.loader_label}",
        f"Detected source: {source.upper()}",
    ]
    if game.disc_number is not None:
        lines.append(f"Disc number: {game.disc_number}")
    if game.disc_version is not None:
        lines.append(f"Disc version: {game.disc_version}")
    if verbose:
        lines.append(f"ID source: {game.id_source}")
    return "\n".join(lines)


def create_shortcut(
    image: Path,
    *,
    game_id: str | None = None,
    name: str | None = None,
    channel_id: str | None = None,
    output: Path | None = None,
    loader: str | None = None,
    source: str | None = None,
    ios: int | None = None,
    advanced: bool = False,
    base_wad: Path | None = None,
    banner: Path | None = None,
    forwarder: Path | None = None,
    write_manifest: bool = False,
    config: AppConfig | None = None,
    log: Log | None = None,
) -> CreateResult:
    """Build one shortcut WAD. The source image is only opened for reading."""
    settings = config or load_config()
    chosen_loader = (loader or settings.loader).strip().lower()
    chosen_source = (source or settings.source).strip().lower()
    chosen_ios = settings.ios if ios is None else ios
    _check_ios(chosen_ios, advanced)
    if chosen_loader != "usbloadergx":
        raise UnsupportedLoaderError(
            f"Loader {chosen_loader!r} is not implemented. V1 supports usbloadergx only."
        )
    note = log or _silent
    note(f"backend usbloadergx source {chosen_source} ios {chosen_ios}")

    game = detect_game(image, game_id=game_id, name=name)
    note(f"game id {game.game_id} from {game.id_source}")
    code = normalize_channel_id(channel_id) if channel_id else channel_id_from_game_id(game.game_id)
    destination = output or Path.cwd() / output_filename(game.title, game.game_id)
    if os.path.lexists(destination):
        raise OutputExistsError(
            f"{destination} already exists. WiiShortcut does not overwrite a WAD."
        )
    sidecar = Path(str(destination) + ".json")
    if write_manifest and os.path.lexists(sidecar):
        raise OutputExistsError(
            f"{sidecar} already exists. WiiShortcut does not overwrite a manifest."
        )
    assert_common_key()
    forwarder_bytes, forwarder_hash = resolve_forwarder(
        loader=chosen_loader,
        source=chosen_source,
        assets_dir=settings.assets_dir,
        explicit=forwarder,
    )
    note(f"forwarder sha256 {forwarder_hash}")
    patched = patch_usbloadergx(forwarder_bytes, game.game_id, chosen_source)
    note("patched game id at CFGUGX+144")
    user_banner = _read_capped(banner, MAX_SECTION_BYTES) if banner else None
    note("banner template static" if user_banner is None else "banner template user")
    channel = assemble_channel(
        name=game.title,
        channel_id=code,
        ios=chosen_ios,
        boot_dol=patched,
        banner=user_banner,
    )
    base = _read_capped(base_wad, MAX_WAD_BYTES) if base_wad else None
    note("packing ticket tmd contents")
    packed = build_wad(
        banner=channel.banner,
        dol=channel.boot_dol,
        channel_id=channel.channel_id,
        game_id=game.game_id,
        loader=chosen_loader,
        source=chosen_source,
        ios=chosen_ios,
        base_wad=base,
    )
    note(f"banner sha1 {hashlib.sha1(channel.banner).hexdigest()}")
    note(f"dol sha1 {hashlib.sha1(channel.boot_dol).hexdigest()}")
    note("content ids 0 and 1, boot index 1")
    atomic_write_wad(destination, packed)
    if write_manifest:
        _write_manifest(
            destination,
            game_id=game.game_id,
            channel_id=channel.channel_id,
            loader=chosen_loader,
            source=chosen_source,
            ios=chosen_ios,
            forwarder_sha256=forwarder_hash,
        )
    return CreateResult(
        game=game,
        channel_id=channel.channel_id,
        loader=chosen_loader,
        source=chosen_source,
        ios=chosen_ios,
        output=destination,
        wad_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        forwarder_sha256=forwarder_hash,
    )


def format_create(result: CreateResult) -> str:
    """Render the human create summary. Progress lines are printed by the CLI."""
    region = result.game.region or "Unknown"
    source = result.source.upper()
    return "\n".join(
        [
            "Game",
            f"  Title       {result.game.title}",
            f"  ID          {result.game.game_id}",
            f"  Format      {result.game.format}",
            f"  Region      {region}",
            "",
            "Channel",
            "  Loader      USB Loader GX",
            f"  Source      {source}",
            f"  IOS         {result.ios}",
            f"  Channel ID  {result.channel_id}",
            "",
            "Building forwarder...",
            "Building channel...",
            "Packing WAD...",
            "Validating...",
            "",
            f"✓ {result.output.name}",
        ]
    )


def scan_library(root: Path) -> list[Path]:
    """Find ``.iso`` and ``.wbfs`` files that stay inside ``root``.

    Symlinks are not followed. A file whose real path leaves the library is
    skipped.
    """
    if not root.is_dir():
        raise InvalidOptionError(f"{root} is not a directory.")
    base = root.resolve()
    found: list[Path] = []
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        current_path = Path(current)
        dirnames[:] = [name for name in dirnames if not (current_path / name).is_symlink()]
        for name in filenames:
            path = current_path / name
            if path.suffix.lower() not in {".iso", ".wbfs"}:
                continue
            if path.is_symlink():
                continue
            try:
                path.resolve().relative_to(base)
            except ValueError:
                continue
            found.append(path)
    return sorted(found)


def plan_batch(
    root: Path,
    output: Path,
    *,
    loader: str,
    source: str,
) -> list[PlannedGame]:
    """Detect every game and refuse collisions before a file is created."""
    planned: list[PlannedGame] = []
    channels: dict[str, str] = {}
    outputs: dict[Path, str] = {}
    for path in scan_library(root):
        game = detect_game(path)
        code = channel_id_from_game_id(game.game_id)
        previous = channels.get(code)
        if previous is not None:
            raise ChannelIdCollisionError(
                f"Channel ID {code} is already used by {previous}. "
                f"{game.game_id} would overwrite that channel. "
                "Pass distinct --channel-id values by building these games one at a time."
            )
        destination = output / output_filename(game.title, game.game_id)
        other = outputs.get(destination)
        if other is not None:
            raise ChannelIdCollisionError(
                f"{game.game_id} and {other} would both write {destination.name}."
            )
        if os.path.lexists(destination):
            raise OutputExistsError(
                f"{destination} already exists. WiiShortcut does not overwrite a WAD."
            )
        channels[code] = game.game_id
        outputs[destination] = game.game_id
        planned.append(PlannedGame(game=game, channel_id=code, output=destination))
    return planned


def run_batch(
    root: Path,
    output: Path,
    *,
    loader: str | None = None,
    source: str | None = None,
    ios: int | None = None,
    advanced: bool = False,
    base_wad: Path | None = None,
    banner: Path | None = None,
    forwarder: Path | None = None,
    write_manifest: bool = False,
    dry_run: bool = False,
    config: AppConfig | None = None,
    log: Log | None = None,
) -> list[PlannedGame] | list[CreateResult]:
    """Preflight the library, then build. ``--dry-run`` returns the plan only."""
    settings = config or load_config()
    chosen_loader = (loader or settings.loader).strip().lower()
    chosen_source = (source or settings.source).strip().lower()
    chosen_ios = settings.ios if ios is None else ios
    _check_ios(chosen_ios, advanced)
    if chosen_loader != "usbloadergx":
        raise UnsupportedLoaderError(
            f"Loader {chosen_loader!r} is not implemented. V1 supports usbloadergx only."
        )
    planned = plan_batch(root, output, loader=chosen_loader, source=chosen_source)
    if dry_run:
        return planned
    assert_common_key()
    resolve_forwarder(
        loader=chosen_loader,
        source=chosen_source,
        assets_dir=settings.assets_dir,
        explicit=forwarder,
    )
    output.mkdir(parents=True, exist_ok=True)
    built: list[CreateResult] = []
    for item in planned:
        built.append(
            create_shortcut(
                Path(item.game.path or ""),
                game_id=item.game.game_id,
                name=item.game.title,
                channel_id=item.channel_id,
                output=item.output,
                loader=chosen_loader,
                source=chosen_source,
                ios=chosen_ios,
                advanced=advanced,
                base_wad=base_wad,
                banner=banner,
                forwarder=forwarder,
                write_manifest=write_manifest,
                config=settings,
                log=log,
            )
        )
    return built


def format_dry_run(planned: list[PlannedGame]) -> str:
    """Render the dry-run listing. This function does not touch the disk."""
    lines = [f"Found {len(planned)} games.", ""]
    for item in planned:
        lines.append(f"{item.game.game_id} {item.game.title}")
    lines.append("")
    lines.append(f"Would create {len(planned)} WAD files.")
    return "\n".join(lines)


def format_batch(results: list[CreateResult], output: Path) -> str:
    """Render the batch summary."""
    lines = [f"Scanning complete. {len(results)} Wii games found.", ""]
    for result in results:
        lines.append(f"✓ {result.game.title}")
    lines.append("")
    lines.append(f"{len(results)}/{len(results)} channels generated successfully.")
    lines.append("")
    lines.append("Output:")
    lines.append(f"  {output}/")
    return "\n".join(lines)


def atomic_write_wad(path: Path, data: bytes) -> ValidationReport:
    """Write a temp file, validate those bytes, then link the WAD into place."""
    if os.path.lexists(path):
        raise OutputExistsError(f"{path} already exists. WiiShortcut does not overwrite a WAD.")
    temporary = write_temp(path.parent, data)
    try:
        report = validate_wad(temporary.read_bytes(), strict=False)
        if not report.ok:
            detail = format_report(report)
            raise InvalidWadError(f"The packed WAD failed validation.\n\n{detail}")
        link_exclusive(temporary, path)
        fsync_dir(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.unlink(missing_ok=True)
    return report


def output_filename(title: str, game_id: str) -> str:
    """Keep spaces, brackets, and colons. Drop controls, slashes, and NULs."""
    cleaned = "".join(char for char in title if char.isprintable() and char not in {"/", "\x00"})
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        cleaned = game_id
    return f"{cleaned} [{game_id}].wad"


def validate_file(path: Path, *, strict: bool = False) -> ValidationReport:
    """Validate a WAD the user already has."""
    if not path.is_file():
        raise InvalidWadError(f"{path} is not a file.")
    size = path.stat().st_size
    if size > MAX_WAD_BYTES:
        raise InvalidWadError(f"{path.name} is {size} bytes, over the 32 MiB limit.")
    return validate_wad(path.read_bytes(), strict=strict)


def _write_manifest(
    wad_path: Path,
    *,
    game_id: str,
    channel_id: str,
    loader: str,
    source: str,
    ios: int,
    forwarder_sha256: str,
) -> None:
    payload = {
        "tool": "wiishortcut",
        "version": __version__,
        "game_id": game_id,
        "channel_id": channel_id,
        "loader": loader,
        "source": source,
        "ios": ios,
        "forwarder_sha256": forwarder_sha256,
        "wad_sha256": hashlib.sha256(wad_path.read_bytes()).hexdigest(),
    }
    sidecar = Path(str(wad_path) + ".json")
    temporary = write_temp(sidecar.parent, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))
    try:
        link_exclusive(temporary, sidecar)
        fsync_dir(sidecar.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.unlink(missing_ok=True)


def _check_ios(ios: int, advanced: bool) -> None:
    if isinstance(ios, bool) or not isinstance(ios, int):
        raise InvalidOptionError("IOS must be an integer.")
    if ios < 3 or ios > 255:
        raise InvalidOptionError(f"IOS {ios} is outside the range 3-255.")
    if ios != 58 and not advanced:
        raise InvalidOptionError(
            "IOS 58 is the WiiGSC 1.1 default. Pass --advanced to select a different IOS."
        )


def _read_capped(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise InvalidWadError(f"{path} is not a file.")
    size = path.stat().st_size
    if size > limit:
        raise InvalidWadError(f"{path.name} is {size} bytes, over the {limit} byte limit.")
    return path.read_bytes()


def _silent(_message: str) -> None:
    return None


def explicit_game_id(value: str | None) -> str | None:
    """Validate a CLI game ID early so the error names the flag."""
    if value is None:
        return None
    return normalize_game_id(value)
