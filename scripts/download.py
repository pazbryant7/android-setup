#!/usr/bin/env python3
"""Compatibility launcher for profile-aware downloads."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from android_setup.cli import main as cli_main  # noqa: E402


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: scripts/download.py PROFILE", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(
        cli_main(["--root", str(REPO_ROOT), "download", sys.argv[1]])
    )
