# License audit

WiiShortcut's own code is MIT. See `pyproject.toml`. Nothing below was copied into `src/` unless the Included column says yes.

The well-known retail common key is not in this repository. A test searches `src/` for that hex and fails if it appears. Nintendo game images, commercial WADs, and system files are not downloaded and are not stored here.

| Resource | Source | License | Redistributable? | Modified? | Included? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| WiiShortcut Python, tests, docs | this repository | MIT | yes | n/a | yes | Host CLI only. |
| libWiiPy 0.6.x | [NinjaCheetah/libWiiPy](https://github.com/NinjaCheetah/libWiiPy), PyPI `libWiiPy` | MIT | yes | no | no, installed by uv | AES, ticket, TMD, U8, IMET, and WAD packing. Pin is `>=0.6.0,<0.7`. |
| WiiGSC C# | [modmii/WiiGSC](https://github.com/modmii/WiiGSC) tag `1.1`, commit `beb2078879867fafd7f13ce0e25d0992b1730644` | GPL-2 (`crapwii/Crap/LICENSE.txt`) | study only | no | no | Behavioral reference. No C# was translated into this tree. |
| `USBLoaderGXForwarder.dol` | WiiGSC 1.1 ModMii Edition zip, `Loaders/`. Author Narolez, modder blackb0x | not stated in the zip | no | no | no | SHA-256 is in `manifest.json`. User copies a local file. |
| `USBLoaderGXForwarderSD.dol` | same zip, `Loaders/` | not stated | no | no | no | Same rule. Contains `--sdmode=1`. |
| `universal-base.wxd` | same zip, `NandLoaders/`. Author Ingunar | not stated. The file contains a Nintendo certificate chain | no | no | no | Optional `--base-wad`. Not shipped. |
| `CFGUSBForwarder.dol`, `WiiFlowForwarder.dol` | same zip | not stated | no | no | no | Not used in V1. |
| Narolez NForwarder sources | `crapwii/Narolez-NForwarder/` inside the WiiGSC tree | a `License` file is present upstream | not vendored | no | no | Not built by the CLI. devkitPPC is not required to run. |
| WadPakk | no canonical public repository with a clear license was identified | unknown | no | no | no | Mentioned as an architectural idea only. No code was copied. |
| Synthetic DOL, ISO, and WBFS fixtures | `tests/support.py` | MIT | yes | yes | yes, tests only | Marker bytes written for tests. Not a bootable loader and not a game. |
| Built-in banner markers | `wiishortcut.channel.banner` | MIT | yes | yes | yes | `WIISHORTCUT-BANNER-V1` and `WIISHORTCUT-ICON-V1`. Not Nintendo banner art. |

`assets install` is a local copy. It is not a download. The CLI does not import `requests` and does not call libWiiPy's NUS downloader.
