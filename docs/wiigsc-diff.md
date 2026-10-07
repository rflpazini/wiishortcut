# What changes between two shortcuts

Compared with synthetic fixtures and with the two official DOL headers measured outside this repository. No game image and no common key are stored here.

## Forwarder DOL

Between the USB and SD builds from WiiGSC 1.1, the stable layout is:

- one `CFGUGX`
- one `CRAPPY`, 144 bytes later
- `TCRP` eight bytes after `CRAPPY`
- the two `apps/usbloader_gx` path strings

The SD build is 128 bytes larger and adds one `--sdmode=1`. After a patch, the only intentional change in a single DOL is those 6 placeholder bytes. A second run with another game ID changes those same 6 bytes. `tools/dol_diff.py` prints the DOL section table and the changed ranges.

`python tools/dol_diff.py a.dol b.dol`

## WAD

Two channels built from the same tool version, with different game IDs and no `SOURCE_DATE_EPOCH`, differ in:

| Region | Why |
| --- | --- |
| Ticket title ID, low 4 bytes | channel code |
| Ticket title-key ciphertext | the key is derived from the game ID and channel ID |
| Ticket and TMD signatures | fakesign brute-forces padding after the title ID changes |
| TMD title ID | same channel code as the ticket |
| Content ciphertext and SHA-1 | banner name and DOL game ID changed |
| IMET names and IMET MD5 | the channel name |

They do not differ in IOS, access rights, boot index, content count, content indexes, or the high 4 bytes of the title ID (`00010001`), unless `--ios`, `--base-wad`, or `--channel-id` says so.

The same inputs and the same tool version, without `SOURCE_DATE_EPOCH`, produce identical bytes. Setting `SOURCE_DATE_EPOCH` changes the 8-byte footer only.

`python tools/wad_diff.py a.wad b.wad` prints section sizes and changed ranges. It does not print ticket or certificate bytes, so a title key cannot show up in the output.

## What WiiGSC changes that this tool does not

Git `Form1.cs` also writes CFG flag bytes at `configPlace + 6` through the following parameter slots. The 1.1 zip says that patch is wrong for USB Loader GX. Those bytes are not written here.

WiiGSC can also copy a disc banner into `00000000.app`. V1 does not extract `opening.bnr` from the game. The built-in banner is a marker, or the user passes `--banner`.
