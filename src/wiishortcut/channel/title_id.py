"""Channel title IDs.

A Wii game ID (RMCE01) is not a channel title ID. WiiGSC 1.1 keeps the
channel type `00010001` from its base WAD and replaces the low 4 bytes with
`U` plus characters 2 through 4 of the game ID. RMCE01 becomes UMCE.

That algorithm is deterministic and avoids the system-menu title space.
Reserved 4-character IDs that already belong to other homebrew channels are
rejected instead of overwritten.
"""

import re

from wiishortcut.errors import ChannelIdCollisionError, InvalidGameIDError

CHANNEL_ID_RE = re.compile(r"^[A-Z0-9]{4}$")
CHANNEL_TYPE = "00010001"

# 4-character codes already used by homebrew the shortcut must not replace.
# UNEO is the official USB Loader GX forwarder. The others are Homebrew Channel
# title IDs used by different HBC releases.
RESERVED_CHANNEL_IDS = {
    "UNEO": "USB Loader GX forwarder",
    "OHBC": "Homebrew Channel",
    "LULZ": "Homebrew Channel (legacy)",
    "JODI": "Homebrew Channel (legacy)",
    "HAXX": "Homebrew Channel (legacy)",
}


def channel_id_from_game_id(game_id: str) -> str:
    """Reproduce the WiiGSC rule: `U` + game_id[1:4]."""
    if len(game_id) != 6:
        raise InvalidGameIDError("A channel ID can only be derived from a 6-character game ID.")
    return normalize_channel_id("U" + game_id[1:4])


def normalize_channel_id(value: str) -> str:
    """Accept a 4-character channel code and reject reserved IDs."""
    candidate = value.strip().upper()
    if not CHANNEL_ID_RE.fullmatch(candidate):
        raise InvalidGameIDError(
            f"Channel ID {value!r} is not valid. Use 4 letters or digits, for example UMCE."
        )
    reason = RESERVED_CHANNEL_IDS.get(candidate)
    if reason is not None:
        raise ChannelIdCollisionError(
            f"Channel ID {candidate} is reserved for {reason}. Pass a different --channel-id."
        )
    return candidate


def full_title_id(channel_id: str, *, title_type: str = CHANNEL_TYPE) -> str:
    """Return the 16-hex-character title ID libWiiPy stores in the TMD."""
    code = normalize_channel_id(channel_id)
    if len(title_type) != 8 or any(ch not in "0123456789abcdefABCDEF" for ch in title_type):
        raise InvalidGameIDError(f"Title type {title_type!r} is not an 8-digit hex prefix.")
    return (title_type + code.encode("ascii").hex()).lower()


def channel_id_from_title_id(title_id_hex: str) -> str:
    """Read the ASCII channel code from a 16-character title ID."""
    if len(title_id_hex) != 16:
        raise InvalidGameIDError(f"Title ID {title_id_hex!r} is not 16 hex characters.")
    try:
        code = bytes.fromhex(title_id_hex)[4:8].decode("ascii")
    except ValueError as exc:
        raise InvalidGameIDError(f"Title ID {title_id_hex!r} is not hex.") from exc
    return normalize_channel_id(code)
