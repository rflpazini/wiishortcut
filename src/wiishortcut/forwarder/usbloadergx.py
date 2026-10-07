"""Patch the WiiGSC 1.1 USB Loader GX forwarder.

WiiGSC does not pass the game ID as a command-line flag of its own. It copies
a forwarder DOL and replaces one 6-byte placeholder, `CRAPPY`, with the game
ID. The same DOL contains one `CFGUGX` config block. On the 1.1 USB and SD
builds the game ID sits 144 bytes after that block.

USB and SD are different DOL files. The SD build contains the USB Loader GX
argument `--sdmode=1`. The USB build does not. WiiGSC 1.1's own config says
the parameter bytes inside `CFGUGX` are not patched reliably for USB Loader GX,
so this patcher leaves that block alone and selects the DOL instead.

The patch refuses to run unless each magic occurs exactly once and the
distance between them is the distance measured on those two builds.
"""

from dataclasses import dataclass

from wiishortcut.errors import InvalidForwarderError, InvalidGameIDError, UnsupportedSourceError
from wiishortcut.game.id import normalize_game_id

DISC_ID_MAGIC = b"CRAPPY"
CONFIG_MAGIC = b"CFGUGX"
CHANNEL_MAGIC = b"TCRP"
SD_ARGUMENT = b"--sdmode=1"
# Measured on USBLoaderGXForwarder.dol and USBLoaderGXForwarderSD.dol from
# WiiGSC 1.1 ModMii Edition: both place CRAPPY 144 bytes after CFGUGX.
DISC_ID_DELTA = 144
LOADER_PATHS = (
    b"apps/usbloader_gx/boot.dol",
    b"apps/usbloadergx/boot.dol",
)


@dataclass(frozen=True)
class ForwarderConfig:
    """What a loader backend needs in order to produce a boot DOL."""

    loader: str
    source: str
    game_id: str


MAX_FORWARDER_BYTES = 8 * 1024 * 1024


def find_all(data: bytes, needle: bytes) -> list[int]:
    """Return every starting offset of `needle`, including overlapping ones."""
    found: list[int] = []
    start = 0
    while True:
        index = data.find(needle, start)
        if index < 0:
            return found
        found.append(index)
        start = index + 1


def patch_usbloadergx(dol: bytes, game_id: str, source: str) -> bytes:
    """Return a copy of `dol` with the disc-ID slot set to `game_id`."""
    normalized = normalize_game_id(game_id)
    device = source.strip().lower()
    if device not in {"usb", "sd"}:
        raise UnsupportedSourceError(
            f"USB Loader GX source {source!r} is not supported. Use usb or sd."
        )
    if not isinstance(dol, (bytes, bytearray)) or not dol:
        raise InvalidForwarderError("The forwarder DOL is empty.")
    if len(dol) > MAX_FORWARDER_BYTES:
        raise InvalidForwarderError("The forwarder DOL is larger than 8 MiB.")

    disc_hits = find_all(dol, DISC_ID_MAGIC)
    config_hits = find_all(dol, CONFIG_MAGIC)
    if len(disc_hits) != 1:
        raise InvalidForwarderError(
            f"Expected exactly one {DISC_ID_MAGIC.decode()} placeholder, found {len(disc_hits)}."
        )
    if len(config_hits) != 1:
        raise InvalidForwarderError(
            f"Expected exactly one {CONFIG_MAGIC.decode()} config block, found {len(config_hits)}."
        )
    disc_at = disc_hits[0]
    config_at = config_hits[0]
    if disc_at - config_at != DISC_ID_DELTA:
        raise InvalidForwarderError(
            f"Game ID placeholder is {disc_at - config_at} bytes after {CONFIG_MAGIC.decode()}. "
            f"The WiiGSC 1.1 USB Loader GX builds use a delta of {DISC_ID_DELTA}."
        )
    sd_hits = find_all(dol, SD_ARGUMENT)
    if device == "sd" and len(sd_hits) != 1:
        raise InvalidForwarderError(
            "The SD forwarder must contain --sdmode=1 exactly once. "
            "This file is not USBLoaderGXForwarderSD.dol."
        )
    if device == "usb" and sd_hits:
        raise InvalidForwarderError(
            "The USB forwarder must not contain --sdmode=1. "
            "Point --source sd at the SD forwarder, or pass the USB DOL."
        )
    for path in LOADER_PATHS:
        if path not in dol:
            raise InvalidForwarderError(
                f"Forwarder is missing the USB Loader GX path {path.decode()}."
            )

    channel_before = len(find_all(dol, CHANNEL_MAGIC))
    patched = bytearray(dol)
    patched[disc_at : disc_at + 6] = normalized.encode("ascii")
    result = bytes(patched)

    if find_all(result, DISC_ID_MAGIC):
        raise InvalidForwarderError("The placeholder was still present after the patch.")
    if result[config_at : config_at + 6] != CONFIG_MAGIC:
        raise InvalidForwarderError("The config magic moved during the patch.")
    if result[disc_at : disc_at + 6] != normalized.encode("ascii"):
        raise InvalidForwarderError("The game ID was not written at the checked offset.")
    if len(find_all(result, CONFIG_MAGIC)) != 1:
        raise InvalidForwarderError("The config block was duplicated or destroyed.")
    if len(find_all(result, CHANNEL_MAGIC)) != channel_before:
        raise InvalidForwarderError("The channel-mode TCRP slot was modified.")
    sd_after = find_all(result, SD_ARGUMENT)
    if device == "sd" and len(sd_after) != 1:
        raise InvalidForwarderError("Patching the game ID removed --sdmode=1.")
    if device == "usb" and sd_after:
        raise InvalidForwarderError("Patching the game ID introduced --sdmode=1.")
    for path in LOADER_PATHS:
        if path not in result:
            raise InvalidForwarderError(f"Patching the game ID removed {path.decode()}.")
    return result


def read_patched_game_id(dol: bytes) -> str:
    """Read the game ID back from a DOL this patcher produced."""
    config_hits = find_all(dol, CONFIG_MAGIC)
    if len(config_hits) != 1:
        raise InvalidForwarderError("Forwarder config block CFGUGX was not found exactly once.")
    start = config_hits[0] + DISC_ID_DELTA
    slot = dol[start : start + 6]
    try:
        return normalize_game_id(slot.decode("ascii"))
    except (UnicodeDecodeError, InvalidGameIDError) as exc:
        raise InvalidForwarderError(
            "The forwarder game ID slot is not a 6-character game ID."
        ) from exc


def detect_source(dol: bytes) -> str:
    """Return `sd` when the DOL carries `--sdmode=1`, otherwise `usb`."""
    hits = find_all(dol, SD_ARGUMENT)
    if len(hits) > 1:
        raise InvalidForwarderError("Forwarder contains --sdmode=1 more than once.")
    return "sd" if hits else "usb"
