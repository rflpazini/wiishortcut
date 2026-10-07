"""Write files without following a symlink onto a game or an existing WAD.

Temporary names come from ``mkstemp``. A WAD is linked into place, so an
existing destination fails instead of being replaced. A filesystem that
cannot hard-link (FAT32 or exFAT) gets an exclusive copy instead. Asset
installs use ``os.replace`` on that new inode, which updates the directory
entry and does not open a predictable ``.tmp`` symlink.
"""

from __future__ import annotations

import errno
import os
import tempfile
from pathlib import Path

from wiishortcut.errors import OutputExistsError

_NO_HARDLINK = {errno.ENOTSUP, errno.EPERM, errno.EOPNOTSUPP}
_EXISTS = "already exists. WiiShortcut does not overwrite a WAD."


def write_temp(directory: Path, data: bytes) -> Path:
    """Write ``data`` to a new file in ``directory`` and fsync it."""
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".wiishortcut-", suffix=".tmp", dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def link_exclusive(temporary: Path, destination: Path) -> None:
    """Publish ``temporary`` as ``destination``. Fail if the name exists."""
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise OutputExistsError(f"{destination} {_EXISTS}") from exc
    except OSError as exc:
        if exc.errno not in _NO_HARDLINK:
            raise
        _copy_exclusive(temporary, destination)


def _copy_exclusive(temporary: Path, destination: Path) -> None:
    """Copy onto a new file. ``O_EXCL`` and ``O_NOFOLLOW`` keep an existing name."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        descriptor = os.open(destination, flags, 0o644)
    except FileExistsError as exc:
        raise OutputExistsError(f"{destination} {_EXISTS}") from exc
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EEXIST}:
            raise OutputExistsError(f"{destination} {_EXISTS}") from exc
        raise
    try:
        with os.fdopen(descriptor, "wb") as handle:
            with temporary.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def replace_file(destination: Path, data: bytes) -> None:
    """Replace ``destination`` with ``data``. The write does not follow a symlink."""
    temporary = write_temp(destination.parent, data)
    try:
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
        fsync_dir(destination.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def fsync_dir(directory: Path) -> None:
    """Flush the directory entry that publishes a new file name."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
