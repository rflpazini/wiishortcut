# Hardware test

Not run yet. The CLI must not install a WAD, write NAND, or talk to a USB loader. Installation stays manual.

Before the first channel:

- Priiloader is installed.
- BootMii is configured when the console supports it.
- A NAND backup exists and you know how to restore it.
- The Homebrew Channel launches.
- USB Loader GX already boots the same game from the Homebrew Channel.
- Only one test WAD is on the SD card.
- `wiishortcut validate --strict` printed `VALID` on the file you are about to install.
- Dolphin has already shown the System Menu surviving this banner, or you accept that this is the first banner trial and you can restore the NAND.

First test, one game:

1. Install that single WAD with your usual WAD manager.
2. Reboot to the System Menu.
3. Confirm the channel name.
4. Launch it. USB Loader GX should open and load the game ID in the WAD.
5. Return to the menu and confirm the console still boots.

Do not batch-install until that one channel is boring. If the menu bricks, use Priiloader or BootMii and the NAND backup. Do not generate a second unknown WAD and install it on top.
