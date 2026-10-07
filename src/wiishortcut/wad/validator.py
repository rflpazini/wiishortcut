"""Validate a WAD from the bytes that were written, not from the live objects.

Section sizes are checked before libWiiPy is asked to parse the file, so a
hostile header cannot request an unbounded read. Decrypt and SHA-1 checks use
libWiiPy. A placeholder banner is reported as a status line, not a warning,
so ``--strict`` does not fail a channel that used the built-in template.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from libWiiPy.archive.u8 import IMETHeader, U8Archive
from libWiiPy.title.title import Title

from wiishortcut.align import align
from wiishortcut.channel.banner import (
    BANNER_MARKER,
    IMET_MAGIC,
    assert_u8_entry_names,
    imet_md5_matches,
    safe_u8_name,
)
from wiishortcut.channel.title_id import RESERVED_CHANNEL_IDS, channel_id_from_title_id
from wiishortcut.errors import InvalidWadError
from wiishortcut.forwarder.usbloadergx import (
    CONFIG_MAGIC,
    LOADER_PATHS,
    detect_source,
    read_patched_game_id,
)
from wiishortcut.wad.dol import parse_dol
from wiishortcut.wad.limits import MAX_CONTENTS, MAX_SECTION_BYTES, MAX_WAD_BYTES

_WAD_MAGIC = bytes.fromhex("0000002049730000")
_HEADER = 0x40


@dataclass(frozen=True)
class Check:
    """One line of the validation report."""

    label: str
    state: str
    note: str = ""


@dataclass
class ValidationReport:
    """The result of reading a WAD back from disk."""

    checks: list[Check] = field(default_factory=list)
    game_id: str | None = None
    channel_id: str | None = None
    ios: int | None = None
    source: str | None = None
    loader_ok: bool = False
    strict: bool = False

    @property
    def ok(self) -> bool:
        failed = any(check.state == "FAIL" for check in self.checks)
        warned = any(check.state == "WARN" for check in self.checks)
        if failed:
            return False
        if self.strict and warned:
            return False
        return True


def validate_wad(data: bytes, *, strict: bool = False) -> ValidationReport:
    """Parse ``data`` and report every structural check."""
    report = ValidationReport(strict=strict)
    try:
        _precheck(data)
    except InvalidWadError as exc:
        report.checks.append(Check("WAD Header", "FAIL", str(exc)))
        return report
    report.checks.append(Check("WAD Header", "OK"))

    title = Title()
    try:
        title.load_wad(data)
    except (TypeError, ValueError, IndexError, OSError, UnicodeError) as exc:
        report.checks.append(Check("Ticket", "FAIL", _safe_error(exc)))
        return report

    _check_ticket_and_tmd(title, report)
    if any(check.state == "FAIL" for check in report.checks):
        return report
    _check_contents(title, report)
    return report


def format_report(report: ValidationReport) -> str:
    """Render the report as plain text. ``VALID`` is the last line when it passed."""
    lines: list[str] = []
    for check in report.checks:
        if check.state == "INFO":
            lines.append(f"{check.label:<24}{check.note}")
        else:
            lines.append(f"{check.label:<24}{check.state}")
    lines.append("")
    lines.append("VALID" if report.ok else "INVALID")
    return "\n".join(lines)


def describe_wad(data: bytes) -> dict[str, object]:
    """Return a small dict for ``wad inspect``. Raises when the WAD will not parse."""
    report = validate_wad(data)
    failed = next((check for check in report.checks if check.state == "FAIL"), None)
    if failed is not None:
        raise InvalidWadError(failed.note or f"{failed.label} is not valid.")
    title = Title()
    try:
        title.load_wad(data)
    except (TypeError, ValueError, IndexError, OSError, UnicodeError) as exc:
        raise InvalidWadError(_safe_error(exc)) from exc
    names = _banner_names(_content_by_record_index(title, 0))
    return {
        "title_id": title.tmd.title_id,
        "channel_id": report.channel_id,
        "ios": title.tmd.ios_version,
        "version": title.tmd.title_version,
        "region": title.tmd.region,
        "access_rights": title.tmd.access_rights,
        "boot_index": title.tmd.boot_index,
        "contents": [
            {
                "index": record.index,
                "content_id": record.content_id,
                "type": record.content_type,
                "size": record.content_size,
                "sha1": record.content_hash.decode(),
            }
            for record in title.tmd.content_records
        ],
        "banner_name": names[1] if len(names) > 1 else "",
        "game_id": report.game_id,
        "source": report.source,
        "valid": report.ok,
    }


def _precheck(data: bytes) -> None:
    if len(data) < _HEADER:
        raise InvalidWadError(f"WAD is {len(data)} bytes. The header needs {_HEADER}.")
    if len(data) > MAX_WAD_BYTES:
        raise InvalidWadError("WAD is larger than 32 MiB.")
    if data[:8] != _WAD_MAGIC:
        raise InvalidWadError("WAD header is not a standard 'Is' WAD.")
    sizes = {
        "cert": _u32(data, 0x08),
        "crl": _u32(data, 0x0C),
        "ticket": _u32(data, 0x10),
        "tmd": _u32(data, 0x14),
        "content": _u32(data, 0x18),
        "meta": _u32(data, 0x1C),
    }
    for name, size in sizes.items():
        if size > MAX_SECTION_BYTES:
            raise InvalidWadError(f"WAD {name} section is {size} bytes, over the 16 MiB limit.")
    if sizes["cert"] == 0 or sizes["ticket"] == 0 or sizes["tmd"] == 0 or sizes["content"] == 0:
        raise InvalidWadError("WAD is missing its certificate chain, ticket, TMD, or contents.")
    offset = _HEADER
    for name in ("cert", "crl", "ticket", "tmd", "content", "meta"):
        if offset % _HEADER != 0:
            raise InvalidWadError(f"WAD {name} section is not aligned to 64 bytes.")
        end = offset + sizes[name]
        if end < offset or end > len(data):
            raise InvalidWadError(f"WAD {name} section does not fit in the file.")
        offset = align(end, _HEADER)


def _check_ticket_and_tmd(title: Title, report: ValidationReport) -> None:
    ticket_id = title.ticket.title_id
    tmd_id = title.tmd.title_id
    report.checks.append(Check("Ticket", "OK"))
    report.checks.append(Check("TMD", "OK"))
    if not isinstance(ticket_id, bytes) or len(ticket_id) != 8:
        report.checks.append(Check("Title ID", "FAIL", "Ticket title ID is not 8 bytes."))
        return
    try:
        tmd_bytes = bytes.fromhex(tmd_id)
    except (TypeError, ValueError):
        report.checks.append(Check("Title ID", "FAIL", "TMD title ID is not hex."))
        return
    if ticket_id != tmd_bytes:
        report.checks.append(Check("Title ID", "FAIL", "ticket/TMD title ID mismatch"))
        return
    try:
        channel_id = channel_id_from_title_id(tmd_id)
    except Exception as exc:
        report.checks.append(Check("Title ID", "FAIL", _safe_error(exc)))
        return
    report.channel_id = channel_id
    if channel_id in RESERVED_CHANNEL_IDS:
        report.checks.append(
            Check(
                "Title ID",
                "FAIL",
                f"{channel_id} is reserved for {RESERVED_CHANNEL_IDS[channel_id]}.",
            )
        )
        return
    report.checks.append(Check("Title ID", "OK"))

    count = title.tmd.num_contents
    records = title.tmd.content_records
    if count != len(records) or count < 1 or count > MAX_CONTENTS:
        report.checks.append(Check("Contents", "FAIL", "Content count is not usable."))
        return
    indexes = [record.index for record in records]
    if len(indexes) != len(set(indexes)):
        report.checks.append(Check("Contents", "FAIL", "Duplicate content indexes."))
        return
    if title.tmd.boot_index != 1 or 1 not in indexes:
        report.checks.append(Check("Contents", "FAIL", "Boot index is not content 1."))
        return
    report.checks.append(Check("Contents", "OK"))
    report.ios = int(title.tmd.ios_version)
    if report.ios == 58:
        report.checks.append(Check("IOS 58", "OK"))
    else:
        report.checks.append(Check(f"IOS {report.ios}", "WARN", "WiiGSC 1.1 uses IOS 58."))
    if int(title.tmd.access_rights) != 3:
        report.checks.append(
            Check("Access rights", "WARN", "AHB and DVD Video access are not both set.")
        )
    if int(title.tmd.region) != 3:
        report.checks.append(
            Check("Region", "WARN", "WiiGSC 1.1 universal base uses region 3 (world).")
        )


def _check_contents(title: Title, report: ValidationReport) -> None:
    decrypted: dict[int, bytes] = {}
    hash_ok = True
    for position, record in enumerate(title.tmd.content_records):
        try:
            decrypted[record.index] = title.get_content_by_index(position)
        except (TypeError, ValueError, IndexError, OSError) as exc:
            hash_ok = False
            report.checks.append(Check("SHA-1", "FAIL", _safe_error(exc)))
            break
        if len(decrypted[record.index]) != record.content_size:
            hash_ok = False
            report.checks.append(
                Check("SHA-1", "FAIL", "Decrypted content size does not match the TMD.")
            )
            break
    if hash_ok:
        report.checks.append(Check("SHA-1", "OK"))
    else:
        return

    banner = decrypted.get(0)
    if banner is None:
        report.checks.append(Check("opening.bnr", "FAIL", "Content index 0 is missing."))
        return
    _check_banner(banner, report)
    boot = decrypted.get(title.tmd.boot_index)
    if boot is None:
        report.checks.append(Check("Forwarder DOL", "FAIL", "Boot content is missing."))
        return
    _check_dol(boot, report)


def _check_banner(banner: bytes, report: ValidationReport) -> None:
    try:
        offset = assert_u8_entry_names(banner)
        archive = U8Archive()
        archive.load(banner[offset:])
    except InvalidWadError as exc:
        report.checks.append(Check("opening.bnr", "FAIL", str(exc)))
        return
    except (TypeError, ValueError, IndexError, UnicodeError, OSError) as exc:
        report.checks.append(Check("opening.bnr", "FAIL", _safe_error(exc)))
        return
    for name in archive.file_name_list:
        if name and not safe_u8_name(name):
            report.checks.append(
                Check("opening.bnr", "FAIL", "U8 entry name is not a relative path.")
            )
            return
    report.checks.append(Check("opening.bnr", "OK"))
    if imet_md5_matches(banner):
        report.checks.append(Check("IMET", "OK"))
    else:
        report.checks.append(Check("IMET", "FAIL", "IMET MD5 does not match the header."))
    if BANNER_MARKER in banner:
        report.checks.append(
            Check("Banner template", "INFO", "structural, not System Menu certified")
        )


def _check_dol(dol: bytes, report: ValidationReport) -> None:
    try:
        parse_dol(dol)
    except InvalidWadError as exc:
        report.checks.append(Check("Forwarder DOL", "FAIL", str(exc)))
        return
    if CONFIG_MAGIC not in dol or any(path not in dol for path in LOADER_PATHS):
        report.checks.append(
            Check("Forwarder DOL", "FAIL", "USB Loader GX markers were not found.")
        )
        return
    try:
        game_id = read_patched_game_id(dol)
        source = detect_source(dol)
    except Exception as exc:
        report.checks.append(Check("Forwarder DOL", "FAIL", _safe_error(exc)))
        return
    report.checks.append(Check("Forwarder DOL", "OK"))
    report.game_id = game_id
    report.source = source
    report.loader_ok = True
    report.checks.append(Check(f"Game ID {game_id}", "OK"))
    report.checks.append(Check("USB Loader GX backend", "OK"))


def _content_by_record_index(title: Title, index: int) -> bytes:
    for position, record in enumerate(title.tmd.content_records):
        if record.index == index:
            return title.get_content_by_index(position)
    raise InvalidWadError(f"Content index {index} is missing.")


def _banner_names(banner: bytes) -> list[str]:
    header = IMETHeader()
    try:
        if (
            len(banner) >= 0x84
            and banner[0x80:0x84] == IMET_MAGIC
            and banner[0x40:0x44] != IMET_MAGIC
        ):
            header.load(banner[0x40:0x640])
        elif len(banner) >= 0x600:
            header.load(banner[:0x600])
        else:
            return []
    except (TypeError, ValueError, IndexError, UnicodeError):
        return []
    if not header.channel_names:
        return []
    return list(header.channel_names)


def _safe_error(exc: Exception) -> str:
    text = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    if len(text) > 180:
        text = text[:180] + "..."
    return text


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")
