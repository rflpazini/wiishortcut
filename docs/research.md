# Research

Sources inspected before the builder was written. Dates below are the files on disk during this work, October 2026.

## What was read

| Tree | Where | Identity |
| --- | --- | --- |
| WiiGSC | local clone of modmii/WiiGSC | tag `1.1`, commit `beb2078879867fafd7f13ce0e25d0992b1730644` |
| WiiGSC 1.1 zip | `WiiGSC.zip` from the GitHub release, unpacked beside the clone | `Readme.txt` header "WiiGSC 1.1", "19/07/2024 XFlak/Ingunar" |
| libWiiPy git | local clone | commit `71ad5b90c659d8a6475c8015e7ea5719d61a1cbb`, version string 1.0.0, not published on PyPI |
| libWiiPy runtime | PyPI | 0.6.0, the version this project imports |

usbloadergx and OpenDolBoot were not cloned. `git clone` stopped on a GitHub username prompt. Their behavior is cited only where a local file shows it.

## Two different "1.1" trees

The git tag and the ModMii release zip are not the same artifact.

- Git `WiiGCC/LoaderConfig.xml` is `version="1.01b"` and still has `<DolContentIndex>`.
- The zip's `LoaderConfig.xml` is `version="1.1"`. It has one nandloader, `universal-base.wxd`, and no `DolContentIndex`.
- Git `WiiGCC/Form1.cs` `PackWad` still reads `nandLoader.DolContentIndex` (around line 1837) and patches CFG flag bytes at `configPlace + 6` onward (around lines 1885-1909).
- The zip's `LoaderConfig.xml` line 17 says: "WiiGSC doesn't patch params correctly, so avoid using any with USB Loader GX and WiiFlow".

WiiShortcut follows the zip, not the flag-byte patch. USB and SD are two DOL files. The CFG block is checked and then left alone.

## How the game ID is injected

Zip `LoaderConfig.xml`:

- `USBLoaderGXForwarder.dol`: `DiscIdPlaceHolder` `CRAPPY`, `ConfigPlaceHolder` `CFGUGX`. Author Narolez, modder blackb0x.
- `USBLoaderGXForwarderSD.dol`: the same placeholders.
- Channel-mode entries use `TitleIdPlaceHolder` `TCRP` and `ConfigPlaceHolder` `UGXWVC`. V1 does not build channel-mode shortcuts.

Git `Form1.cs` `searchAndReplaceInArray` (line 2447) finds the placeholder with `findArrayInArray` and copies the new bytes over the first hit. It returns false when the offset is `<= 0`, so a hit at offset 0 is rejected.

Measured on the zip's DOL files, without copying those files into this repo:

| File | Size | SHA-256 | `CFGUGX` | `CRAPPY` | Delta |
| --- | --- | --- | --- | --- | --- |
| `USBLoaderGXForwarder.dol` | 303364 | `ff31340547ddf9eaad6ccc10491333fe59770d0fe978fc233e504c0399d7d671` | 266368 | 266512 | 144 |
| `USBLoaderGXForwarderSD.dol` | 303492 | `7702a375d7bd35354e51997c14f861f42e369e706fc8c1704b9b2d7cb1302cfb` | 266496 | 266640 | 144 |

The SD file contains `--sdmode=1` once. The USB file contains it zero times. Both contain `apps/usbloader_gx/boot.dol` and `apps/usbloadergx/boot.dol`. `TCRP` sits 8 bytes after `CRAPPY`.

WiiShortcut replaces that one 6-byte slot and then checks that `CRAPPY` is gone, `CFGUGX` is still one hit, `TCRP` was not touched, and the `--sdmode=1` count still matches the selected source.

The exact `argv` the DOL builds for USB Loader GX was not disassembled. The public loader treats a 4 to 6 character argument as a quick-boot title ID and honors `-sdmode=` for SD configs. This tool does not invent extra arguments.

## Channel title ID

Git `Form1.cs` sets the channel code in four places (lines 828, 1665, 2464, 2478):

```text
"U" + discId.Substring(1, 3)
```

`RMCE01` becomes `UMCE`. The full title ID keeps the channel type `00010001` and replaces the low 4 bytes. WiiShortcut does the same and rejects `UNEO`, `OHBC`, `LULZ`, `JODI`, and `HAXX`. `UNEO` is the official USB Loader GX "return to" forwarder. A shortcut must not reuse it.

Batch collisions are an error. The tool does not pick a different ID silently.

## Base WAD and nandloader

The zip ships one nandloader, `NandLoaders/universal-base.wxd` (4096 bytes, author Ingunar). `Nand-Readme.txt` calls these "bannerless wad packages containing nand loaders".

Measured structure of that file, fields only:

- Header type `Is`. Certificate chain, ticket, TMD, two 64-byte content stubs, 64-byte footer.
- Title `00010001` plus ASCII `USPP`. IOS `000000010000003a` (IOS 58).
- `access_rights` 3 (AHB and DVD video). Region 3. `vwii` 0. Boot index 1. Two contents, both type `0x0001`.
- Ticket issuer `Root-CA00000001-XS00000003`. TMD issuer `Root-CA00000001-CP00000004`.

The TMD `vwii` flag is 0. Any vWii path is inside the DOL (OpenDolBoot / nboot, credited to DacoTaco in WiiGSC materials), not a second TMD flag. V1 does not reimplement nboot. `--base-wad` keeps the user's certificate chain and high title-ID word, replaces the low 4 bytes and the two contents, sets IOS and access rights, and fakesigns.

The default path does not need that file. It builds a ticket, a TMD, and a zero-modulus certificate chain with libWiiPy, then fakesigns. That chain is larger than Nintendo's 2560-byte chain because libWiiPy's cert padding differs. It round-trips through `CertificateChain.load`. It has not been installed in Dolphin or on a Wii.

## What libWiiPy 0.6.0 already does

Used, not reimplemented:

- `encrypt_title_key`, `encrypt_content`, ticket and TMD `dump` / `fakesign`
- `Title.load_wad`, `dump_wad`, `set_title_id`, `set_content`, `get_content_by_index`
- `U8Archive.load`, `IMETHeader`, `pack_u8`
- retail common key inside libWiiPy

Gaps found in 0.6.0 and handled here:

- `Title.add_content` fails on an empty content list. The builder calls `encrypt_content` and `content.add_enc_content` with indexes 0 and 1.
- `pack_u8(generate_imet=True)` does not write an IMET header. The builder calls `IMETHeader.create` and prepends `dump()`.
- `U8Archive` extraction joins archive names to a directory. The validator never extracts. It rejects `..`, absolute names, and NUL.
- Content SHA-1 is stored as 40 ASCII hex bytes. `get_content_by_index` compares that digest and raises `ValueError` with both hashes on mismatch. The validator turns that into a short `InvalidWadError` and does not print it as a key.

Git main's 1.0.0 is not on PyPI. The project stays on 0.6.x until a 1.0 release exists. `src/` does not import `requests` even though libWiiPy depends on it.

## IOS 58 and AHB

The 1.1 zip's universal base asks for IOS 58 and sets access rights to 3. That is the default here. Another IOS requires `--advanced` and is a warning, so `validate --strict` fails it. The host tool does not reload IOS. The installed channel's TMD is what the System Menu reads.

## USB versus SD

| Source | DOL | `--sdmode=1` |
| --- | --- | --- |
| `usb` | `USBLoaderGXForwarder.dol` | absent |
| `sd` | `USBLoaderGXForwarderSD.dol` | exactly one |

No CFG flag byte is written.

## Disc header

ISO: 6-byte ID at 0, disc number at 6, version at 7, magic `0x5D1C9EA3` at 0x18, 64-byte title at 0x20. WBFS: magic `WBFS`, sector shift at byte 8 (accepted range 9 through 15), disc header at `1 << shift`. Reads are bounded. The file is never loaded whole and never written.

Game ID order: `--game-id`, then the header, then `[GAMEID]` in the path, then the filename. A filename is not accepted when the image cannot be parsed. The region character is index 3: E USA, P PAL, J Japan, K Korea, W Taiwan.

## Unknowns

- The byte-level `argv` inside the Narolez DOL.
- Whether YAWM, Dolphin, or a Wii accepts the zero-modulus certificate chain.
- Whether the structural banner is safe on the System Menu. It is labeled as not certified.
- OpenDolBoot's current source. It was not cloned. nboot was not reimplemented.
- Whether the 2024 `WiiGSC.exe` still consults `DolContentIndex`. The zip's XML no longer has the field. This tool writes content indexes 0 and 1 itself.
