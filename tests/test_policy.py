"""The repository must not carry Nintendo key material or a network client."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
# Split so the well-known retail key is not one contiguous string in this file.
KNOWN_KEY = "ebe42a22" + "5e8593e4" + "48d9c545" + "7381aaf7"


def test_source_has_no_common_key_and_no_downloader() -> None:
    for path in SOURCE.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        assert KNOWN_KEY not in text
        assert "download_title" not in text
        assert "import requests" not in text
        assert "common-key.bin" not in text


def test_gitignore_ignores_forwarders_and_nandloaders() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.dol" in ignored
    assert "*.wxd" in ignored
