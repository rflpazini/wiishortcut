# WiiShortcut

Native macOS CLI that builds a Wii channel shortcut for USB Loader GX.
Point it at a `.iso` or `.wbfs` file. It writes a `.wad`. It does not modify the game, install anything on a Wii, or use the network.

```bash
uv run wiishortcut inspect game.wbfs
uv run wiishortcut create game.wbfs
uv run wiishortcut validate "Game Name [GAMEID].wad"
```

The bootable forwarder DOL is not in this repository. Copy it from a local WiiGSC 1.1 ModMii Edition install:

```bash
uv run wiishortcut assets install /path/to/USBLoaderGXForwarder.dol
uv run wiishortcut assets install /path/to/USBLoaderGXForwarderSD.dol
```

`assets install` checks the SHA-256 against `src/wiishortcut/resources/manifest.json` and refuses every other file.

## Requirements

- macOS on Apple Silicon, or any host that can run CPython 3.13
- [uv](https://docs.astral.sh/uv/)
- Python 3.13 (uv installs it)
- A WiiGSC 1.1 USB Loader GX forwarder DOL, kept on your machine

No Windows, Wine, Mono, or devkitPPC is required to run the CLI.

## Standalone binary

On an Apple Silicon Mac, this builds one arm64 executable. It does not need a Python install on the machine that runs it.

```bash
uv run python scripts/build_macos_arm64.py
file dist/wiishortcut
./dist/wiishortcut --version
```

`file` must report `Mach-O 64-bit executable arm64`, and `lipo -archs` must print only `arm64`. The script deletes the binary when that check fails. PyInstaller 6 is the packer. Nuitka would need a C toolchain and a long compile for the same kind of binary, so the release script uses PyInstaller. The binary is ad-hoc signed. It is not a Developer ID signature and it is not in git. `dist/` stays ignored.

The build refuses to run when `uname -m` is not `arm64`.

```bash
git clone <this repo>
cd wiishortcut
uv sync --group dev
uv run wiishortcut --version
```

`--version` prints the tool version and the installed libWiiPy version.

## Commands

| Command | What it does |
| --- | --- |
| `inspect IMAGE` | Read the game ID, title, and region. |
| `create IMAGE` | Build one shortcut WAD. |
| `validate FILE` | Check a WAD. `--strict` turns warnings into errors. |
| `batch DIRECTORY` | Build one WAD per game. `--dry-run` writes nothing. |
| `doctor` | Platform, assets, and key status. Keys are never printed. |
| `assets list` | Manifest entries and their hashes. |
| `assets verify` | Compare installed DOLs with the manifest. |
| `assets install FILE` | Copy a local DOL after the hash matches. |
| `wad inspect FILE` | Title ID, IOS, contents, banner name. |

Useful flags: `--game-id`, `--name`, `--channel-id`, `--output`, `--loader`, `--source usb|sd`, `--ios` (58 unless `--advanced`), `--base-wad`, `--banner`, `--forwarder`, `--json`, `--manifest`. Put `-v`, `-vv`, and `--debug` before the command: `wiishortcut -v inspect game.wbfs`.

`create` refuses to overwrite an existing WAD. Batch checks every game ID and channel ID before it writes the first file. Two games that would share a channel ID stop the batch.

## Defaults

USB Loader GX, USB storage, IOS 58, a structural banner, and a channel ID of `U` plus characters 2 through 4 of the game ID. `RMCE01` becomes channel `UMCE`.

Config lives in `~/Library/Application Support/WiiShortcut/config.toml` on macOS, or `$XDG_CONFIG_HOME/wiishortcut/config.toml` elsewhere. Cache is `~/Library/Caches/wiishortcut/`. Override the config file or its directory with `WIISHORTCUT_CONFIG`, and the cache with `WIISHORTCUT_CACHE_DIR`.

Do not put a common key in `config.toml`. libWiiPy already has the retail key it uses to pack title keys. If you set `WII_COMMON_KEY_HEX` or `keys.toml`, the value must match that key or the command stops. The key is never printed.

`SOURCE_DATE_EPOCH` writes an 8-byte footer so a build can be reproduced. Without it, the same inputs produce the same WAD bytes.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. `doctor` also returns 0 when something is missing. Its JSON `ok` field says which. |
| 1 | Unexpected error. |
| 2 | Bad input, bad option, or the output file already exists. |
| 3 | Missing or mismatched forwarder, or a common key that does not match. |
| 4 | The WAD failed validation. |
| 5 | Two games want the same channel ID. |

`--json` prints only JSON on stdout, including errors. `--debug` adds a traceback.

## What this version does not do

The built-in banner is a marked structural template. It is not a System Menu animation. Pass `--banner` with an `opening.bnr` you already trust before you install a channel.

The default certificate chain is generated with zero RSA moduli and then fakesigned. That has not been proven in Dolphin, YAWM ModMii Edition, or on a Wii. Pass `--base-wad` with your own `universal-base.wxd` when you want that certificate chain instead. Do not commit that file.

Dolphin install and a real Wii boot are documented and not yet run. See `docs/dolphin-testing.md` and `docs/hardware-test.md`.

## Docs

- `docs/research.md` covers the WiiGSC 1.1 pipeline and what libWiiPy already does.
- `docs/licenses.md` is the license audit.
- `docs/architecture.md`, `docs/wad-format.md`, and `docs/forwarders.md` describe the implementation.
- `docs/wiigsc-diff.md` records what changes between two shortcut WADs.
