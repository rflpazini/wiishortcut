"""User configuration, paths, and the common-key check.

macOS stores config and installed forwarders in
``~/Library/Application Support/WiiShortcut/`` and cache in
``~/Library/Caches/wiishortcut/``. Other platforms use the XDG directories.

``WIISHORTCUT_CONFIG`` may point at a ``config.toml`` file or at the directory
that contains one. ``WIISHORTCUT_CACHE_DIR`` overrides the cache directory.

A common key is never required for normal use. libWiiPy already carries the
retail key it uses to encrypt title keys. If ``WII_COMMON_KEY_HEX`` or
``keys.toml`` is set, that value must match libWiiPy. This module compares
the bytes and never prints either value.
"""

from __future__ import annotations

import hmac
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from wiishortcut.errors import ConfigError, MissingKeyError, WiiShortcutError

DEFAULT_LOADER = "usbloadergx"
DEFAULT_SOURCE = "usb"
DEFAULT_IOS = 58
_KEY_NAMES = {"common_key", "common_key_hex", "title_key"}


@dataclass(frozen=True)
class AppConfig:
    """Resolved defaults. Explicit CLI flags still win over these."""

    loader: str
    source: str
    ios: int
    config_path: Path
    assets_dir: Path
    cache_dir: Path


def application_support_dir() -> Path:
    """Return the directory that holds ``config.toml`` and ``assets/``."""
    override = os.environ.get("WIISHORTCUT_CONFIG")
    if override:
        path = Path(override).expanduser()
        if path.suffix == ".toml":
            return path.parent
        return path
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WiiShortcut"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "wiishortcut"


def cache_dir() -> Path:
    """Return the cache directory. Nothing in the MVP has to write here."""
    override = os.environ.get("WIISHORTCUT_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "wiishortcut"
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "wiishortcut"


def config_file() -> Path:
    """Return the config.toml path, whether or not the file exists."""
    override = os.environ.get("WIISHORTCUT_CONFIG")
    if override:
        path = Path(override).expanduser()
        if path.suffix == ".toml":
            return path
        return path / "config.toml"
    return application_support_dir() / "config.toml"


def load_config() -> AppConfig:
    """Load defaults. A missing file is fine. A key stored here is not."""
    path = config_file()
    data: dict[str, object] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Cannot read {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must be a TOML table.")
        if _contains_key_name(data):
            raise MissingKeyError(
                "Refusing to read a common key from config.toml. "
                "Move it to keys.toml or set WII_COMMON_KEY_HEX."
            )
    loader = str(data.get("default_loader", DEFAULT_LOADER))
    source = str(data.get("default_source", DEFAULT_SOURCE))
    ios_value = data.get("default_ios", DEFAULT_IOS)
    if isinstance(ios_value, bool) or not isinstance(ios_value, int):
        raise ConfigError("default_ios must be an integer.")
    support = path.parent
    return AppConfig(
        loader=loader,
        source=source,
        ios=ios_value,
        config_path=path,
        assets_dir=support / "assets",
        cache_dir=cache_dir(),
    )


def key_status() -> str:
    """Return ``libWiiPy``, ``configured``, or ``mismatch``. Never a key byte."""
    try:
        supplied = _supplied_key()
    except WiiShortcutError:
        return "mismatch"
    if supplied is None:
        return "libWiiPy"
    if _matches_library_key(supplied):
        return "configured"
    return "mismatch"


def assert_common_key() -> None:
    """Fail closed when a user-supplied key does not match libWiiPy."""
    status = key_status()
    if status == "mismatch":
        raise MissingKeyError(
            "The configured common key does not match the retail common key "
            "libWiiPy uses to pack the WAD. Remove WII_COMMON_KEY_HEX or keys.toml "
            "to use the library key, or install the matching retail key."
        )


def _contains_key_name(value: object) -> bool:
    """Return whether a TOML value stores a common-key field at any depth."""
    if isinstance(value, dict):
        if _KEY_NAMES.intersection(value):
            return True
        return any(_contains_key_name(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key_name(item) for item in value)
    return False


def _supplied_key() -> bytes | None:
    """Return the user key, if one was configured. Mismatched sources fail."""
    env_raw = os.environ.get("WII_COMMON_KEY_HEX")
    file_raw = _key_from_files()
    env_key = _parse_key(env_raw) if env_raw is not None else None
    file_key = _parse_key(file_raw) if file_raw is not None else None
    if env_key is not None and file_key is not None and not _bytes_equal(env_key, file_key):
        raise MissingKeyError(
            "WII_COMMON_KEY_HEX and keys.toml do not contain the same common key."
        )
    if env_key is not None:
        return env_key
    return file_key


def _key_from_files() -> str | None:
    candidates = [
        config_file().parent / "keys.toml",
        Path.home() / ".config" / "wiishortcut" / "keys.toml",
    ]
    found: list[str] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.expanduser()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            data = tomllib.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Cannot read {resolved}: {exc}") from exc
        if not isinstance(data, dict) or "common_key_hex" not in data:
            continue
        value = data["common_key_hex"]
        if not isinstance(value, str):
            raise MissingKeyError("keys.toml common_key_hex must be a string.")
        found.append(value)
    if not found:
        return None
    first = found[0]
    if any(item != first for item in found[1:]):
        raise MissingKeyError("The common key files do not match each other.")
    return first


def _parse_key(text: str) -> bytes:
    cleaned = "".join(text.split()).lower().removeprefix("0x")
    if len(cleaned) != 32 or any(char not in "0123456789abcdef" for char in cleaned):
        raise MissingKeyError("A common key must be 32 hex characters.")
    return bytes.fromhex(cleaned)


def _matches_library_key(supplied: bytes) -> bool:
    from libWiiPy.title.commonkeys import get_common_key

    library = get_common_key(0, False)
    return _bytes_equal(supplied, library)


def _bytes_equal(left: bytes, right: bytes) -> bool:
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)
