"""Game ID and channel-name validation."""

import re

from wiishortcut.errors import InvalidChannelNameError, InvalidGameIDError

GAME_ID_RE = re.compile(r"^[A-Z0-9]{6}$")
CHANNEL_ID_RE = re.compile(r"^[A-Z0-9]{4}$")
BRACKET_RE = re.compile(r"\[([A-Z0-9]{6})\]")

# The forwarder image uses this exact 6-byte placeholder. A real game must
# not collide with it, or the patcher cannot prove the slot changed.
PLACEHOLDER_GAME_ID = "CRAPPY"

# IMET stores each language as 42 UTF-16BE code units (84 bytes).
IMET_NAME_UNITS = 42


def normalize_game_id(value: str) -> str:
    """Accept a 6-character game ID. Reject the forwarder placeholder."""
    candidate = value.strip().upper()
    if not GAME_ID_RE.fullmatch(candidate):
        raise InvalidGameIDError(
            f"Game ID {value!r} is not valid. A Wii game ID is 6 letters or digits, "
            "for example RMCE01."
        )
    if candidate == PLACEHOLDER_GAME_ID:
        raise InvalidGameIDError(
            "CRAPPY is the USB Loader GX forwarder placeholder, not a game ID."
        )
    return candidate


def normalize_channel_name(name: str) -> str:
    """Strip a channel name and reject values that do not fit IMET."""
    cleaned = " ".join(name.replace("\x00", " ").split())
    if not cleaned:
        raise InvalidChannelNameError("The channel name is empty.")
    encoded = cleaned.encode("utf-16-be")
    if len(encoded) > IMET_NAME_UNITS * 2:
        raise InvalidChannelNameError(
            f"The channel name is {len(encoded) // 2} UTF-16 units. "
            f"IMET allows {IMET_NAME_UNITS}. Pass a shorter --name."
        )
    return cleaned
