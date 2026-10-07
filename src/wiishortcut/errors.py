"""Errors the CLI turns into a message and an exit code."""


class WiiShortcutError(Exception):
    """Base error. The default exit code is a generic failure."""

    exit_code = 1


class InvalidGameImageError(WiiShortcutError):
    """The ISO or WBFS header could not be read safely."""

    exit_code = 2


class InvalidGameIDError(WiiShortcutError):
    """A game ID or channel ID failed validation."""

    exit_code = 2


class InvalidChannelNameError(WiiShortcutError):
    """The channel name does not fit the IMET field."""

    exit_code = 2


class InvalidWadError(WiiShortcutError):
    """A WAD, banner, or packed section is structurally invalid."""

    exit_code = 4


class InvalidForwarderError(WiiShortcutError):
    """The forwarder DOL does not match the USB Loader GX layout."""

    exit_code = 2


class MissingKeyError(WiiShortcutError):
    """A supplied common key is missing, malformed, or does not match."""

    exit_code = 3


class AssetIntegrityError(WiiShortcutError):
    """A required forwarder is missing or its SHA-256 does not match."""

    exit_code = 3


class ChannelIdCollisionError(WiiShortcutError):
    """Two games want the same channel ID, or the ID is reserved."""

    exit_code = 5


class UnsupportedLoaderError(WiiShortcutError):
    """The requested loader backend is not implemented."""

    exit_code = 2


class UnsupportedSourceError(WiiShortcutError):
    """The requested game source is not implemented for this loader."""

    exit_code = 2


class OutputExistsError(WiiShortcutError):
    """Refusing to overwrite an existing WAD."""

    exit_code = 2


class InvalidOptionError(WiiShortcutError):
    """A CLI or config option is outside the supported range."""

    exit_code = 2


class ConfigError(WiiShortcutError):
    """The config file is missing a required piece or cannot be parsed."""

    exit_code = 3
