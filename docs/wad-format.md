# WAD layout

libWiiPy writes the WAD. This project checks the result.

Header magic is `00 00 00 20 49 73 00 00` (`Is`). Six big-endian sizes follow: certificate chain, CRL, ticket, TMD, content, footer. Each section starts on a 64-byte boundary. `align` and `pad` in `wiishortcut.align` are the helpers used when this code reasons about that modulus. libWiiPy pads its own sections the same way.

Limits before any parse: 32 MiB for the file, 16 MiB for one section, 64 contents, 8 MiB for a DOL. A size that does not fit the file is a header failure. The parser does not allocate from the size field alone.

A channel this tool builds:

| Field | Value |
| --- | --- |
| Title type | `00010001` |
| Title code | 4 ASCII bytes, for example `UMCE` |
| IOS | `00000001` + IOS number. Default 58 (`0000003a`). |
| Region | 3 (world), matching the universal base |
| Title type bytes | `00000000` |
| Access rights | 3 (AHB and DVD video) |
| `vwii` | 0 |
| Boot index | 1 |
| Content 0 | banner, type `0x0001`, index 0 |
| Content 1 | DOL, type `0x0001`, index 1 |
| Ticket | 676 bytes before fakesign |
| Signatures | zeroed, then libWiiPy fakesign |

The validator requires `ticket.title_id == bytes.fromhex(tmd.title_id)`. A mismatch is `ticket/TMD title ID mismatch`.

IMET is 1536 bytes: 64 zero bytes, magic `IMET` at 0x40, ten UTF-16BE names of 42 units, MD5 over the header with the hash field zeroed. The U8 archive starts at 0x600. An IMET at 0x80 (U8 at 0x640) is also accepted. Names are rewritten in all ten languages and the MD5 is recomputed. A name longer than 42 UTF-16 units is an error. Pass `--name`.

The built-in U8 holds `icon.bin`, `banner.bin`, and `sound.bin`, each with an IMD5 header. The payloads are the markers `WIISHORTCUT-BANNER-V1`, `WIISHORTCUT-ICON-V1`, and two zero bytes. Validation reports that banner as INFO: structural, not System Menu certified. INFO does not fail `--strict`.

`--banner` must already be an IMET+U8 file of at most 8 MiB. Only the names and the MD5 change.

Content encryption and the title-key wrap stay inside libWiiPy. This repository has no AES implementation.
