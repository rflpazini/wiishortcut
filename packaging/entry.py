"""Entry point for the frozen macOS binary.

PyInstaller executes this file. The installed console script is a separate
path and stays `wiishortcut.cli:app`.
"""

from wiishortcut.cli import app

if __name__ == "__main__":
    app()
