"""Locate the USB Loader GX forwarder by SHA-256.

The DOL files are not shipped in this repository. ``manifest.json`` records
the SHA-256 of the WiiGSC 1.1 builds. ``assets install`` copies a local file
only after the hash matches. ``create`` refuses every other file, including a
test fixture marked ``bootable: false``.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.resources
import json
from dataclasses import dataclass
from pathlib import Path

from wiishortcut.errors import AssetIntegrityError, UnsupportedLoaderError, UnsupportedSourceError
from wiishortcut.forwarder import usbloadergx
from wiishortcut.fs import replace_file


@dataclass(frozen=True)
class Asset:
    """One forwarder record from the manifest."""

    name: str
    sha256: str
    filename: str
    source: str
    license: str
    included: bool
    platform: str
    loader: str
    source_device: str
    bootable: bool


def load_manifest() -> dict[str, Asset]:
    """Read the packaged manifest. This is a data file, not a download."""
    text = (
        importlib.resources.files("wiishortcut.resources")
        .joinpath("manifest.json")
        .read_text(encoding="utf-8")
    )
    raw = json.loads(text)
    assets: dict[str, Asset] = {}
    for name, item in raw.items():
        assets[name] = Asset(
            name=name,
            sha256=str(item["sha256"]).lower(),
            filename=str(item["filename"]),
            source=str(item.get("source", "")),
            license=str(item.get("license", "")),
            included=bool(item.get("included", False)),
            platform=str(item.get("platform", "")),
            loader=str(item.get("loader", "")),
            source_device=str(item.get("source_device", "")),
            bootable=bool(item.get("bootable", False)),
        )
    return assets


def asset_for(loader: str, source: str) -> Asset:
    """Return the bootable manifest entry for this loader and source."""
    loader_name = loader.strip().lower()
    device = source.strip().lower()
    if loader_name != "usbloadergx":
        raise UnsupportedLoaderError(
            f"Loader {loader!r} is not implemented. V1 supports usbloadergx only."
        )
    if device not in {"usb", "sd"}:
        raise UnsupportedSourceError(f"Source {source!r} is not implemented. Use usb or sd.")
    matches = [
        asset
        for asset in load_manifest().values()
        if asset.loader == loader_name and asset.source_device == device and asset.bootable
    ]
    if len(matches) != 1:
        raise AssetIntegrityError(
            f"The manifest does not contain one bootable {device} forwarder for {loader_name}."
        )
    return matches[0]


def accept_forwarder(data: bytes, asset: Asset) -> str:
    """Return the SHA-256 when ``data`` is the bootable file ``asset`` names."""
    if not asset.bootable:
        raise AssetIntegrityError(
            f"{asset.filename} is not marked bootable. Refusing to pack it into a channel."
        )
    digest = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(digest, asset.sha256):
        raise AssetIntegrityError(
            f"{asset.filename} SHA-256 does not match the manifest.\nExpected {asset.sha256}."
        )
    return digest


def resolve_forwarder(
    *,
    loader: str,
    source: str,
    assets_dir: Path,
    explicit: Path | None = None,
) -> tuple[bytes, str]:
    """Load the forwarder from ``--forwarder`` or from the assets directory."""
    asset = asset_for(loader, source)
    if explicit is not None:
        data = _read_file(explicit)
        return data, accept_forwarder(data, asset)
    installed = assets_dir / asset.filename
    if not installed.is_file():
        raise AssetIntegrityError(
            f"The {source.upper()} USB Loader GX forwarder is not installed.\n\n"
            f"Expected SHA-256:\n  {asset.sha256}\n\n"
            "Copy it from a local WiiGSC 1.1 ModMii Edition install:\n\n"
            f"  wiishortcut assets install /path/to/{asset.filename}"
        )
    data = _read_file(installed)
    return data, accept_forwarder(data, asset)


def install_asset(source: Path, assets_dir: Path) -> Asset:
    """Copy ``source`` into the assets directory when its hash is known."""
    data = _read_file(source)
    digest = hashlib.sha256(data).hexdigest()
    match = next(
        (
            asset
            for asset in load_manifest().values()
            if asset.bootable and hmac.compare_digest(digest, asset.sha256)
        ),
        None,
    )
    if match is None:
        raise AssetIntegrityError(
            "This file is not a known bootable USB Loader GX forwarder. "
            "WiiShortcut accepts only the WiiGSC 1.1 USB and SD builds."
        )
    destination = assets_dir / match.filename
    replace_file(destination, data)
    installed = destination.read_bytes()
    accept_forwarder(installed, match)
    return match


def verify_installed(assets_dir: Path) -> list[tuple[Asset, str]]:
    """Return ``(asset, status)`` for every manifest entry.

    Status is ``ok``, ``missing``, or ``mismatch``. Entries that are not
    bootable are reported as ``not-bootable`` and are not required.
    """
    results: list[tuple[Asset, str]] = []
    for asset in load_manifest().values():
        if not asset.bootable:
            results.append((asset, "not-bootable"))
            continue
        path = assets_dir / asset.filename
        if not path.is_file():
            results.append((asset, "missing"))
            continue
        try:
            size = path.stat().st_size
            if size > usbloadergx.MAX_FORWARDER_BYTES:
                results.append((asset, "mismatch"))
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            results.append((asset, "mismatch"))
            continue
        if hmac.compare_digest(digest, asset.sha256):
            results.append((asset, "ok"))
        else:
            results.append((asset, "mismatch"))
    return results


def _read_file(path: Path) -> bytes:
    if not path.is_file():
        raise AssetIntegrityError(f"{path} is not a file.")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AssetIntegrityError(f"Cannot read {path}: {exc}") from exc
    limit = usbloadergx.MAX_FORWARDER_BYTES
    if size > limit:
        raise AssetIntegrityError(
            f"{path.name} is {size} bytes, over the {limit} byte forwarder limit."
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AssetIntegrityError(f"Cannot read {path}: {exc}") from exc
