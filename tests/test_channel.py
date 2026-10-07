"""Channel IDs follow the WiiGSC rule and stay out of reserved title IDs."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from libWiiPy.archive.u8 import U8Archive

from wiishortcut.channel.banner import build_static_banner, imet_md5_matches, retitle_banner
from wiishortcut.channel.title_id import (
    RESERVED_CHANNEL_IDS,
    channel_id_from_game_id,
    channel_id_from_title_id,
    full_title_id,
    normalize_channel_id,
)
from wiishortcut.errors import ChannelIdCollisionError, InvalidChannelNameError, InvalidGameIDError
from wiishortcut.game.id import normalize_channel_name


def test_wii_gsc_channel_id() -> None:
    assert channel_id_from_game_id("RMCE01") == "UMCE"
    assert full_title_id("UMCE") == "00010001554d4345"
    assert channel_id_from_title_id("00010001554d4345") == "UMCE"


@pytest.mark.parametrize("reserved", sorted(RESERVED_CHANNEL_IDS))
def test_reserved_channel_ids_are_rejected(reserved: str) -> None:
    with pytest.raises(ChannelIdCollisionError):
        normalize_channel_id(reserved)


def test_game_that_would_land_on_uneo_is_rejected() -> None:
    with pytest.raises(ChannelIdCollisionError):
        channel_id_from_game_id("ANEO01")


def test_bad_channel_ids() -> None:
    with pytest.raises(InvalidGameIDError):
        normalize_channel_id("UM")
    with pytest.raises(InvalidGameIDError):
        channel_id_from_game_id("RMCE")
    with pytest.raises(InvalidGameIDError):
        full_title_id("UMCE", title_type="zz")
    with pytest.raises(InvalidGameIDError):
        channel_id_from_title_id("abcd")


def test_imet_name_is_written_in_every_language_and_hashed() -> None:
    banner = build_static_banner("Mario Kart Wii")
    assert imet_md5_matches(banner)
    archive = U8Archive()
    archive.load(banner)
    assert archive.imet_header.channel_names == ["Mario Kart Wii"] * 10
    renamed = retitle_banner(banner, "Custom Name")
    assert banner[0x600:] == renamed[0x600:]
    assert imet_md5_matches(renamed)
    archive.load(renamed)
    assert archive.imet_header.channel_names == ["Custom Name"] * 10


def test_channel_name_must_fit_imet() -> None:
    assert normalize_channel_name("A" * 42) == "A" * 42
    with pytest.raises(InvalidChannelNameError):
        normalize_channel_name("A" * 43)
    with pytest.raises(InvalidChannelNameError):
        build_static_banner("   ")


@given(
    st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=4,
        max_size=4,
    )
)
def test_channel_id_roundtrip(code: str) -> None:
    if code in RESERVED_CHANNEL_IDS:
        return
    assert channel_id_from_title_id(full_title_id(code)) == code
