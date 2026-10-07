"""Build a native arm64 wiishortcut binary with PyInstaller.

Run from the repository root:

    uv run python scripts/build_macos_arm64.py

Nuitka can also compile this package, but it needs a C toolchain and a long
compile for the same Mach-O result. PyInstaller 6 packs the already-tested
interpreter, libWiiPy, and manifest.json into one arm64 executable.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_command(python: str) -> list[str]:
    """Return the PyInstaller argv. The last item is the entry script."""
    entry = ROOT / "packaging" / "entry.py"
    return [
        python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "wiishortcut",
        "--target-arch",
        "arm64",
        "--paths",
        str(ROOT / "src"),
        "--collect-all",
        "wiishortcut",
        "--collect-all",
        "libWiiPy",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build"),
        str(entry),
    ]


def is_thin_arm64(lipo_stdout: str) -> bool:
    """Accept only `lipo -archs` output that is exactly arm64."""
    return lipo_stdout.split() == ["arm64"]


def verify_binary(binary: Path) -> int:
    """Print `file` output and delete the binary unless it is thin arm64."""
    info = subprocess.run(
        ["file", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    archs = subprocess.run(
        ["lipo", "-archs", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    print(info.stdout, end="")
    if is_thin_arm64(archs.stdout):
        return 0
    binary.unlink(missing_ok=True)
    print("The binary is not a thin arm64 Mach-O.", file=sys.stderr)
    return 1


def main() -> int:
    """Build the binary and refuse the result unless it is thin arm64."""
    if platform.machine() != "arm64":
        print(
            f"Refusing to build. This host is {platform.machine()}, and the "
            "release binary must be arm64.",
            file=sys.stderr,
        )
        return 2
    subprocess.run(build_command(sys.executable), cwd=ROOT, check=True)
    return verify_binary(ROOT / "dist" / "wiishortcut")


if __name__ == "__main__":
    raise SystemExit(main())
