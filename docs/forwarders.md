# Forwarders

V1 has one backend, USB Loader GX. A later loader would implement the same three steps: build a config, patch a DOL, validate the patch. `ChannelBuilder` only sees the finished DOL.

## Patch

`patch_usbloadergx` copies the DOL and writes the game ID at one checked offset.

Preconditions, all required:

- source is `usb` or `sd`
- file is non-empty and at most 8 MiB
- `CRAPPY` occurs once
- `CFGUGX` occurs once
- `CRAPPY` starts 144 bytes after `CFGUGX`
- SD files contain `--sdmode=1` once, USB files contain it zero times
- both loader paths are present: `apps/usbloader_gx/boot.dol` and `apps/usbloadergx/boot.dol`

The 6 bytes at the `CRAPPY` offset become the game ID. The function then checks the result:

- `CRAPPY` is gone
- `CFGUGX` is unchanged and still unique
- the 6 bytes at the offset are the game ID
- the `TCRP` count is unchanged
- the `--sdmode=1` count is unchanged
- both loader paths are still present

The input buffer is not modified. `CRAPPY` is rejected as a game ID so the placeholder cannot be confused with a title.

`--forwarder` is accepted only when the file's SHA-256 equals the bootable manifest entry for that source. A record with `bootable: false` is refused. There is no environment variable that skips the hash.

## Installed files

`assets install` hashes the local file, matches it to one bootable manifest row, writes a private temp file, sets mode `0644`, and replaces the installed name. It does not follow a predictable `.tmp` symlink. `assets verify` prints `ok`, `missing`, `mismatch`, or `not-bootable`. A missing bootable file is exit 3 for `verify` and for `create`. `doctor` still exits 0 and reports the forwarder as MISSING so a fresh install can be diagnosed.

`create` resolves the DOL once, patches a copy, and never writes the DOL back to the assets directory.

## What is not patched

CFG flag bytes at `CFGUGX+6` and the following parameter slots. WiiGSC 1.1's own config says those bytes are not reliable for USB Loader GX. USB versus SD is the choice of DOL.

`TCRP` is the channel-mode placeholder. V1 does not write it.
