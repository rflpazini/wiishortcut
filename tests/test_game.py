"""Game ID detection reads a header and does not trust a filename by itself."""

from pathlib import Path

import pytest
from tests.support import write_iso, write_wbfs

from wiishortcut.errors import InvalidChannelNameError, InvalidGameIDError, InvalidGameImageError
from wiishortcut.game.detect import detect_game, game_id_from_path, title_from_path
from wiishortcut.game.id import normalize_channel_name, normalize_game_id
from wiishortcut.game.iso import read_bounded, read_iso
from wiishortcut.game.wbfs import read_wbfs
from wiishortcut.pipeline import output_filename


def test_wbfs_header_beats_a_misleading_name(tmp_path: Path) -> None:
    image = write_wbfs(tmp_path / "NOTTHE.wbfs", "RMCE01", "Mario Kart Wii")
    game = detect_game(image)
    assert game.game_id == "RMCE01"
    assert game.title == "Mario Kart Wii"
    assert game.region == "USA"
    assert game.format == "WBFS"
    assert game.id_source == "wbfs-header"
    assert game.disc_number == 0


def test_iso_header_and_regions(tmp_path: Path) -> None:
    image = write_iso(tmp_path / "game.iso", "RMCP01", "Mario Kart Wii")
    game = read_iso(image)
    assert game.game_id == "RMCP01"
    assert game.region == "PAL"
    assert game.format == "ISO"
    japan = write_iso(tmp_path / "jp.iso", "RMCJ01", "Kart")
    assert read_iso(japan).region == "Japan"
    korea = write_iso(tmp_path / "kr.iso", "RMCK01", "Kart")
    assert read_iso(korea).region == "Korea"
    taiwan = write_iso(tmp_path / "tw.iso", "RMCW01", "Kart")
    assert read_iso(taiwan).region == "Taiwan"
    other = write_iso(tmp_path / "xx.iso", "RMCZ01", "Kart")
    assert read_iso(other).region is None


def test_explicit_id_overrides_a_readable_header(tmp_path: Path) -> None:
    image = write_wbfs(tmp_path / "game.wbfs", "RMCE01", "Mario Kart Wii")
    game = detect_game(image, game_id="rsbe01", name="Custom")
    assert game.game_id == "RSBE01"
    assert game.title == "Custom"
    assert game.id_source == "override"
    assert game.region == "USA"


def test_corrupt_image_is_not_rescued_by_its_filename(tmp_path: Path) -> None:
    folder = tmp_path / "Mario Kart Wii [RMCE01]"
    folder.mkdir()
    image = folder / "RMCE01.wbfs"
    image.write_bytes(b"this is not a disc")
    with pytest.raises(InvalidGameIDError, match="WBFS metadata") as caught:
        detect_game(image)
    message = str(caught.value)
    assert "directory name" in message
    assert "filename" in message
    assert "--game-id" not in message
    with pytest.raises(InvalidGameImageError):
        detect_game(image, game_id="RMCE01")


def test_a_placeholder_header_uses_the_directory_or_an_explicit_id(tmp_path: Path) -> None:
    folder = tmp_path / "Mario Kart Wii [RMCE01]"
    image = write_wbfs(folder / "DISC01.wbfs", "CRAPPY", "Mario Kart Wii")
    game = detect_game(image)
    assert game.game_id == "RMCE01"
    assert game.title == "Mario Kart Wii"
    assert game.format == "WBFS"
    assert game.id_source == "path"
    assert game.disc_number == 0
    override = detect_game(image, game_id="RSBE01")
    assert override.game_id == "RSBE01"
    assert override.id_source == "override"
    assert override.title == "Mario Kart Wii"
    assert override.format == "WBFS"


def test_a_placeholder_header_can_use_the_filename(tmp_path: Path) -> None:
    image = write_iso(tmp_path / "RMCE01.iso", "CRAPPY", "Demo")
    game = detect_game(image)
    assert game.game_id == "RMCE01"
    assert game.id_source == "filename"
    assert game.title == "Demo"
    assert game.format == "ISO"


def test_a_placeholder_header_without_a_path_id_is_rejected(tmp_path: Path) -> None:
    image = write_wbfs(tmp_path / "notes.wbfs", "CRAPPY", "Demo")
    with pytest.raises(InvalidGameIDError, match="not a Wii game ID"):
        detect_game(image)


def test_an_invalid_bracket_falls_through_to_the_filename(tmp_path: Path) -> None:
    folder = tmp_path / "Game [CRAPPY]"
    image = write_wbfs(folder / "RMCE01.wbfs", "CRAPPY", "Demo")
    game = detect_game(image)
    assert game.game_id == "RMCE01"
    assert game.id_source == "filename"
    placeholder = write_wbfs(tmp_path / "CRAPPY.wbfs", "CRAPPY", "Demo")
    with pytest.raises(InvalidGameIDError, match="not a Wii game ID"):
        detect_game(placeholder)


def test_a_readable_header_still_beats_the_directory_id(tmp_path: Path) -> None:
    folder = tmp_path / "Other [RSBE01]"
    image = write_wbfs(folder / "RMCE01.wbfs", "RMCE01", "Mario Kart Wii")
    game = detect_game(image)
    assert game.game_id == "RMCE01"
    assert game.id_source == "wbfs-header"


def test_path_helpers_and_rejection() -> None:
    path = Path("/Volumes/WII/wbfs/Mario Kart Wii [RMCE01]/RMCE01.wbfs")
    assert game_id_from_path(path) == "RMCE01"
    assert title_from_path(path) == "Mario Kart Wii"
    assert game_id_from_path(Path("RMCE01.wbfs")) == "RMCE01"
    assert game_id_from_path(Path("notes.txt")) is None
    with pytest.raises(InvalidGameIDError):
        normalize_game_id("nope")
    with pytest.raises(InvalidGameIDError):
        normalize_game_id("CRAPPY")
    with pytest.raises(InvalidChannelNameError):
        normalize_channel_name("   ")
    with pytest.raises(InvalidChannelNameError):
        normalize_channel_name("A" * 43)


def test_channel_name_limits() -> None:
    assert normalize_channel_name("  Mario   Kart  ") == "Mario Kart"
    assert normalize_channel_name("A" * 42) == "A" * 42


def test_wbfs_rejects_a_bad_sector_shift(tmp_path: Path) -> None:
    path = tmp_path / "bad.wbfs"
    path.write_bytes(b"WBFS" + b"\x00" * 12)
    with pytest.raises(InvalidGameImageError, match="sector shift"):
        read_wbfs(path)


def test_iso_rejects_a_bad_magic(tmp_path: Path) -> None:
    path = tmp_path / "bad.iso"
    path.write_bytes(b"\x00" * 128)
    with pytest.raises(InvalidGameImageError, match="magic"):
        read_iso(path)


def test_reads_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / "short.bin"
    path.write_bytes(b"abc")
    with pytest.raises(InvalidGameImageError):
        read_bounded(path, 0, 8)
    with pytest.raises(InvalidGameImageError):
        read_bounded(path, -1, 1)
    with pytest.raises(InvalidGameImageError):
        read_bounded(path, 0, 1000, limit=10)
    path.write_bytes(b"abcdefghijklmnop")
    with pytest.raises(InvalidGameImageError):
        read_bounded(path, 8, 4, limit=10)


def test_filename_keeps_colon_and_drops_controls() -> None:
    name = output_filename("The Legend of Zelda: Twilight Princess", "RZDE01")
    assert name == "The Legend of Zelda: Twilight Princess [RZDE01].wad"
    assert "/" not in output_filename("a/b\nc", "RMCE01")


def test_image_bytes_do_not_change(tmp_path: Path) -> None:
    image = write_wbfs(tmp_path / "game.wbfs", "RMCE01", "Mario Kart Wii")
    before = image.read_bytes()
    detect_game(image)
    assert image.read_bytes() == before
