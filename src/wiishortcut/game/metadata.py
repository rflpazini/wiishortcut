"""Game identity types shared by the detectors and the CLI."""

from dataclasses import dataclass

# The fourth character of a Wii game ID is the region.
REGION_BY_CODE = {
    "E": "USA",
    "P": "PAL",
    "J": "Japan",
    "K": "Korea",
    "W": "Taiwan",
}


@dataclass(frozen=True)
class GameMetadata:
    """What the rest of the pipeline needs from a game image."""

    game_id: str
    title: str
    region: str | None
    format: str
    id_source: str
    disc_number: int | None = None
    disc_version: int | None = None
    path: str | None = None

    @property
    def loader_label(self) -> str:
        return "USB Loader GX"


def region_from_game_id(game_id: str) -> str | None:
    """Map the region character of a 6-character game ID."""
    if len(game_id) != 6:
        return None
    return REGION_BY_CODE.get(game_id[3])
