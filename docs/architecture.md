# Architecture

Three stages stay separate. The game reader does not know about WADs. The channel builder does not know how USB Loader GX finds a game. The WAD builder receives a banner and a DOL that are already configured.

```text
image -> GameMetadata -> patched DOL -> banner + DOL -> WAD bytes -> validate from disk -> rename
```

| Module | Job |
| --- | --- |
| `game.detect` | ISO or WBFS header, then path hints. |
| `forwarder.usbloadergx` | One placeholder patch with magic, delta, and post-checks. |
| `forwarder.assets` | Manifest hashes. Missing or mismatched files are exit 3. |
| `channel.banner` | IMET names and MD5. U8 payload is not relocated by hand. |
| `channel.builder` | Name, channel ID, banner, boot DOL. |
| `wad.builder` | Ticket, TMD, encrypted contents, fakesign, optional base WAD. |
| `wad.validator` | Re-read the bytes and report FAIL, WARN, or INFO. |
| `pipeline` | Create, batch preflight, atomic write. |
| `cli` | Typer commands. `--json` is the only stdout in JSON mode. |

`create_shortcut` writes a private temp file in the destination directory, validates those bytes, and fsyncs. It then hard-links the final name. On a filesystem that cannot link, such as FAT32 or exFAT, it copies onto a new file opened with `O_CREAT|O_EXCL|O_NOFOLLOW` and fsyncs that file. A failure deletes the temp file. An existing destination, including a symlink, is an error. There is no `--force`.

Batch scans with `os.walk(followlinks=False)` and drops a path whose real location leaves the library. It plans every channel ID and output name first. `--dry-run` returns that plan and does not create the output directory. A real batch creates the directory only after the forwarder and the common-key check succeed.

The title key is `sha256("wiishortcut-v1|{loader}|{source}|{game_id}|{channel_id}")[:16]`. It is not logged. `SOURCE_DATE_EPOCH` is the only input that changes the footer.

Pack-time validation uses `strict=False` so `--ios 56 --advanced` can be written. `validate --strict` still fails that WAD.

Logs may include the game ID, the forwarder SHA-256, content indexes, and content SHA-1. They must not include a common key, a title key, or game bytes.
