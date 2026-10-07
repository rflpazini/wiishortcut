"""Assemble the two files a channel needs: the banner and the boot DOL.

The channel builder does not know how USB Loader GX finds a game. It receives
a DOL that the forwarder backend has already configured.
"""

from __future__ import annotations

from dataclasses import dataclass

from wiishortcut.channel.banner import build_static_banner, retitle_banner
from wiishortcut.channel.title_id import normalize_channel_id
from wiishortcut.game.id import normalize_channel_name


@dataclass(frozen=True)
class ChannelFiles:
    """The decrypted contents that go into the WAD."""

    name: str
    channel_id: str
    ios: int
    banner: bytes
    boot_dol: bytes


def assemble_channel(
    *,
    name: str,
    channel_id: str,
    ios: int,
    boot_dol: bytes,
    banner: bytes | None = None,
) -> ChannelFiles:
    """Build or retitle the banner and pair it with the boot DOL."""
    cleaned = normalize_channel_name(name)
    code = normalize_channel_id(channel_id)
    if banner is None:
        packed_banner = build_static_banner(cleaned)
    else:
        packed_banner = retitle_banner(banner, cleaned)
    return ChannelFiles(
        name=cleaned,
        channel_id=code,
        ios=ios,
        banner=packed_banner,
        boot_dol=boot_dol,
    )
