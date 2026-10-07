"""Build a two-content channel WAD with libWiiPy.

The default path does not start from a Nintendo WAD. It writes a structural
certificate chain whose RSA moduli are zero, a v0 ticket, and a TMD, then
asks libWiiPy to fakesign both. That chain is not Nintendo's certificate and
has not been proven on a Wii or in Dolphin. ``--base-wad`` keeps the
certificate chain from a WAD the user already has, such as WiiGSC's
``universal-base.wxd``, and only replaces the title ID and the two contents.

AES stays inside libWiiPy. The title key is derived, never logged, and never
read from a Nintendo disc.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from libWiiPy.title.cert import (
    Certificate,
    CertificateChain,
    CertificateKeyType,
    CertificateType,
)
from libWiiPy.title.crypto import encrypt_content, encrypt_title_key
from libWiiPy.title.ticket import Ticket
from libWiiPy.title.title import Title
from libWiiPy.title.tmd import TMD

from wiishortcut.channel.title_id import full_title_id
from wiishortcut.errors import InvalidWadError
from wiishortcut.wad.limits import MAX_WAD_BYTES

_SIGNATURE_TYPE = (0x00010001).to_bytes(4, "big")
_TICKET_ISSUER = "Root-CA00000001-XS00000003"
_TMD_ISSUER = "Root-CA00000001-CP00000004"
_CONTENT_NORMAL = 0x0001
_REGION_WORLD = 3
_ACCESS_AHB_AND_DVD = 3


@dataclass(frozen=True)
class _PlayLimit:
    limit_type: int
    maximum_usage: int


def derive_title_key(*, game_id: str, channel_id: str, source: str, loader: str) -> bytes:
    """Return 16 deterministic bytes. The same inputs always pack the same key."""
    material = f"wiishortcut-v1|{loader}|{source}|{game_id}|{channel_id}".encode()
    return hashlib.sha256(material).digest()[:16]


def build_wad(
    *,
    banner: bytes,
    dol: bytes,
    channel_id: str,
    game_id: str,
    loader: str,
    source: str,
    ios: int,
    base_wad: bytes | None = None,
) -> bytes:
    """Pack a channel and return the WAD bytes. The caller writes them."""
    if ios < 3 or ios > 255:
        raise InvalidWadError(f"IOS {ios} is outside the range 3-255.")
    if len(banner) == 0 or len(dol) == 0:
        raise InvalidWadError("The banner and the boot DOL are both required.")
    if base_wad is not None:
        wad = _build_from_base(
            base_wad,
            banner=banner,
            dol=dol,
            channel_id=channel_id,
            ios=ios,
        )
    else:
        wad = _build_from_scratch(
            banner=banner,
            dol=dol,
            channel_id=channel_id,
            game_id=game_id,
            loader=loader,
            source=source,
            ios=ios,
        )
    _apply_epoch(wad)
    packed = wad.dump_wad()
    if len(packed) > MAX_WAD_BYTES:
        raise InvalidWadError("The packed WAD is larger than 32 MiB.")
    return packed


def _build_from_scratch(
    *,
    banner: bytes,
    dol: bytes,
    channel_id: str,
    game_id: str,
    loader: str,
    source: str,
    ios: int,
) -> Title:
    title_id = full_title_id(channel_id)
    raw_title_id = bytes.fromhex(title_id)
    title_key = derive_title_key(
        game_id=game_id,
        channel_id=channel_id,
        source=source,
        loader=loader,
    )
    encrypted_key = encrypt_title_key(title_key, 0, raw_title_id, False)
    title = Title()
    title.cert_chain = _certificate_chain()
    title.ticket = _ticket(raw_title_id, encrypted_key)
    title.tmd = _tmd(title_id, ios)
    for index, blob, content_id in ((0, banner, 0), (1, dol, 1)):
        encrypted = encrypt_content(blob, title_key, index)
        digest = hashlib.sha1(blob).hexdigest().encode()
        title.content.add_enc_content(
            encrypted,
            content_id,
            index,
            _CONTENT_NORMAL,
            len(blob),
            digest,
        )
    title.tmd.content_records = title.content.content_records
    title.tmd.num_contents = title.content.num_contents
    title.tmd.boot_index = 1
    title.fakesign()
    _require_fakesigned(title)
    return title


def _build_from_base(
    base_wad: bytes,
    *,
    banner: bytes,
    dol: bytes,
    channel_id: str,
    ios: int,
) -> Title:
    if len(base_wad) > MAX_WAD_BYTES:
        raise InvalidWadError("The base WAD is larger than 32 MiB.")
    title = Title()
    try:
        title.load_wad(base_wad)
    except (TypeError, ValueError, IndexError, OSError) as exc:
        raise InvalidWadError(f"The base WAD could not be parsed: {exc}") from exc
    if title.tmd.num_contents != 2 or len(title.content.content_records) != 2:
        raise InvalidWadError("The base WAD must contain exactly 2 contents (banner and DOL).")
    if title.content.content_records[1].index != 1:
        raise InvalidWadError("The base WAD boot content is not at content index 1.")
    high = title.tmd.title_id[:8]
    if len(high) != 8:
        raise InvalidWadError("The base WAD title ID has no 4-byte type prefix.")
    _require_retail_ticket(title)
    try:
        title.set_title_id(high + channel_id.encode("ascii").hex())
        title.set_content(banner, 0, content_type=_CONTENT_NORMAL)
        title.set_content(dol, 1, content_type=_CONTENT_NORMAL)
    except (TypeError, ValueError, IndexError) as exc:
        raise InvalidWadError(
            "The base WAD could not be updated. Its ticket must decrypt with the retail common key."
        ) from exc
    title.tmd.ios_tid = f"00000001{ios:08x}"
    title.tmd.ios_version = ios
    title.tmd.region = _REGION_WORLD
    title.tmd.access_rights = _ACCESS_AHB_AND_DVD
    title.tmd.boot_index = 1
    title.tmd.vwii = 0
    title.tmd.num_contents = 2
    title.fakesign()
    _require_fakesigned(title)
    return title


def _require_retail_ticket(title: Title) -> None:
    """Refuse a dev ticket or a Korean or vWii common-key index.

    libWiiPy decrypts every other index with the retail key. WiiGSC 1.1's
    universal base stores index 224 and still decrypts with that key.
    """
    ticket = getattr(title, "ticket", None)
    if ticket is None:
        return
    if bool(ticket.is_dev) or int(ticket.common_key_index) in {1, 2}:
        raise InvalidWadError(
            "The base WAD could not be updated. Its ticket must decrypt with the retail common key."
        )


def _certificate_chain() -> CertificateChain:
    chain = CertificateChain()
    chain.ca_cert = _certificate("ca")
    chain.tmd_cert = _certificate("cp")
    chain.ticket_cert = _certificate("xs")
    # Round-trip through libWiiPy so a chain it cannot parse never leaves here.
    packed = chain.dump()
    loaded = CertificateChain()
    try:
        loaded.load(packed)
    except (TypeError, ValueError, IndexError) as exc:
        raise InvalidWadError(f"The generated certificate chain is not parseable: {exc}") from exc
    chain.ca_cert = loaded.ca_cert
    chain.tmd_cert = loaded.tmd_cert
    chain.ticket_cert = loaded.ticket_cert
    return chain


def _certificate(kind: str) -> Certificate:
    cert = Certificate()
    cert.pub_key_id = 0
    cert.pub_key_modulus = 0
    cert.pub_key_exponent = 65537
    if kind == "ca":
        cert.type = CertificateType.RSA_4096
        cert.signature = b"\x00" * 0x200
        cert.issuer = "Root"
        cert.pub_key_type = CertificateKeyType.RSA_4096
        cert.child_name = "CA00000001"
        return cert
    cert.type = CertificateType.RSA_2048
    cert.signature = b"\x00" * 0x100
    cert.issuer = "Root-CA00000001"
    cert.pub_key_type = CertificateKeyType.RSA_2048
    cert.child_name = "CP00000004" if kind == "cp" else "XS00000003"
    return cert


def _ticket(raw_title_id: bytes, encrypted_title_key: bytes) -> Ticket:
    ticket = Ticket()
    ticket.signature_type = _SIGNATURE_TYPE
    ticket.signature = b"\x00" * 256
    ticket.signature_issuer = _TICKET_ISSUER
    ticket.ecdh_data = b"\x00" * 60
    ticket.ticket_version = 0
    ticket.title_key_enc = encrypted_title_key
    ticket.ticket_id = b"\x00" * 8
    ticket.console_id = 0
    ticket.title_id = raw_title_id
    ticket.unknown1 = b"\x00" * 2
    ticket.title_version = 1
    ticket.permitted_titles = b"\x00" * 4
    ticket.permit_mask = b"\x00" * 4
    ticket.title_export_allowed = 0
    ticket.common_key_index = 0
    ticket.unknown2 = b"\x00" * 48
    ticket.content_access_permissions = b"\x00" * 64
    ticket.title_limits_list = [_PlayLimit(0, 0) for _ in range(8)]
    ticket.is_dev = False
    if len(ticket.dump()) != 676:
        raise InvalidWadError("The generated ticket is not 676 bytes.")
    return ticket


def _tmd(title_id: str, ios: int) -> TMD:
    tmd = TMD()
    tmd.signature_type = _SIGNATURE_TYPE
    tmd.signature = b"\x00" * 256
    tmd.signature_issuer = _TMD_ISSUER
    tmd.tmd_version = 0
    tmd.ca_crl_version = 0
    tmd.signer_crl_version = 0
    tmd.vwii = 0
    tmd.ios_tid = f"00000001{ios:08x}"
    tmd.ios_version = ios
    tmd.title_id = title_id
    tmd.title_type = b"\x00" * 4
    tmd.group_id = 0
    tmd.region = _REGION_WORLD
    tmd.ratings = b"\x00" * 16
    tmd.reserved1 = b"\x00" * 12
    tmd.ipc_mask = b"\x00" * 12
    tmd.reserved2 = b"\x00" * 18
    tmd.access_rights = _ACCESS_AHB_AND_DVD
    tmd.title_version = 1
    tmd.boot_index = 1
    tmd.minor_version = 0
    return tmd


def _require_fakesigned(title: Title) -> None:
    if not title.tmd.get_is_fakesigned() or not title.ticket.get_is_fakesigned():
        raise InvalidWadError("libWiiPy did not fakesign the ticket and the TMD.")


def _apply_epoch(title: Title) -> None:
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw is None or raw == "":
        return
    try:
        epoch = int(raw)
    except ValueError as exc:
        raise InvalidWadError("SOURCE_DATE_EPOCH must be an integer.") from exc
    if epoch < 0 or epoch > 0xFFFFFFFFFFFFFFFF:
        raise InvalidWadError("SOURCE_DATE_EPOCH is out of range.")
    title.wad.set_meta_data(epoch.to_bytes(8, "big"))
