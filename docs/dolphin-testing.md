# Dolphin testing

Not run yet. On 2026-10-03 this Mac had no `Dolphin.app` and no `~/Library/Application Support/Dolphin` NAND. Do not download a System Menu or a NAND to fill that gap. Use a NAND you already dumped. Do this before any Wii install. The host CLI only writes a file. It does not drive Dolphin.

1. Build one WAD from a disc you already have: `wiishortcut create game.wbfs`.
2. `wiishortcut validate --strict` must print `VALID`.
3. Confirm the report's game ID, channel ID, IOS 58, and source.
4. In Dolphin, install the WAD into a disposable NAND, not the NAND you use for anything else.
5. Boot the System Menu. The channel should appear under the name you set. A banner that freezes the menu means the template is not safe. Stop. Do not install that file on a Wii.
6. Launch the channel. USB Loader GX should start and receive the game ID. The structural banner is not certified, so a failure here is still an open question, not a pass.

If the install is rejected, retry with `--base-wad` pointing at your local `universal-base.wxd`. That keeps a certificate chain the ModMii base already used. It does not make the banner a real animation.

Record the Dolphin version, the WAD's SHA-256 from the `--manifest` sidecar, and whether the zero-key build or the base-WAD build got further.
