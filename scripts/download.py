#!/usr/bin/env python3
"""
download.py — fetch latest APKs from GitHub and backups from pCloud.

Run from repo root:
    python3 scripts/download.py

Files are saved under their original upstream names:
    apks/    shizuku-v<version>-release.apk
             app-arm64-v8a-release.apk
    backups/ obtainium-export-<timestamp>-auto.json
             <date> - foldersync.db          ← extracted from the zip
    tools/   uad-ng-linux                    ← desktop binary, chmod +x

Skip logic
──────────
• GitHub APKs / UAD-NG: the remote filename encodes the version (e.g.
  shizuku-v13.5.0-release.apk).  If that exact file already exists locally
  and is non-empty we skip the download — no re-fetch needed.
• Backups (Obtanium / FolderSync): timestamps change on every export, so
  we always fetch the latest and never skip them.
"""

import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib import (
    already_downloaded,
    download_file,
    extract_archive,
    github_asset_url,
    log_error,
    log_info,
    log_ok,
    log_section,
    log_warn,
    pcloud_latest_file,
)

# ── Config ────────────────────────────────────────────────────────────────────

APKS_DIR = REPO_ROOT / "apks"
BACKUPS_DIR = REPO_ROOT / "backups"
TOOLS_DIR = REPO_ROOT / "tools"

SHIZUKU_REPO = "RikkaApps/Shizuku"
SHIZUKU_APK_PATTERN = "shizuku-"
SHIZUKU_APK_EXCLUDE = ""

OBTANIUM_REPO = "ImranR98/Obtainium"
OBTANIUM_APK_PATTERN = "app-arm64-v8a-release.apk"
OBTANIUM_APK_EXCLUDE = "fdroid"
OBTANIUM_APK_FALLBACK = "app-release.apk"

UADNG_REPO = "Universal-Debloater-Alliance/universal-android-debloater-next-generation"
UADNG_ASSET_PATTERN = "uad-ng-linux"
UADNG_ASSET_EXCLUDE = "checksum"  # skip the .checksum sidecar files

PCLOUD_OBTANIUM_CODE = "kZNVmI5ZFByIzeOIGNHBxuJhhO6GJpw5tWGk"
PCLOUD_FOLDERSYNC_CODE = "kZkxYI5ZafGQ9nFsLR0cxk1SfXSwaHEUWaFV"
OBTANIUM_BACKUP_PATTERN = "obtainium-export"
FOLDERSYNC_BACKUP_PATTERN = "foldersync.db.zip"

# ── Individual download tasks ─────────────────────────────────────────────────


def download_shizuku() -> bool:
    log_section("Shizuku APK")

    result = github_asset_url(
        SHIZUKU_REPO, SHIZUKU_APK_PATTERN, exclude=SHIZUKU_APK_EXCLUDE
    )
    if result is None:
        log_error("Could not resolve Shizuku APK URL")
        return False

    url, filename = result
    dest = APKS_DIR / filename
    if already_downloaded(dest):
        return True
    return download_file(url, dest)


def download_obtanium() -> bool:
    log_section("Obtanium APK")

    result = github_asset_url(
        OBTANIUM_REPO, OBTANIUM_APK_PATTERN, exclude=OBTANIUM_APK_EXCLUDE
    )
    if result is None:
        log_warn("arm64 variant not found — falling back to universal APK")
        result = github_asset_url(OBTANIUM_REPO, OBTANIUM_APK_FALLBACK)
    if result is None:
        log_error("Could not resolve Obtanium APK URL")
        return False

    url, filename = result
    dest = APKS_DIR / filename
    if already_downloaded(dest):
        return True
    return download_file(url, dest)

def download_obtanium_backup() -> bool:
    # Always fetch — backup filenames are timestamped, latest is always newer.
    log_section("Obtanium backup")

    result = pcloud_latest_file(PCLOUD_OBTANIUM_CODE, OBTANIUM_BACKUP_PATTERN)
    if result is None:
        log_error("Could not resolve Obtanium backup URL")
        return False

    url, filename = result
    return download_file(url, BACKUPS_DIR / filename)


def download_foldersync_backup() -> bool:
    """
    Download the FolderSync backup archive and extract its contents into
    BACKUPS_DIR so the raw database file (not the archive) is what gets pushed
    to the phone.

    Always fetch — backup filenames are timestamped, latest is always newer.

    If the upstream format ever changes from .zip to .rar / .tar.gz / etc.:
      1. Update FOLDERSYNC_BACKUP_PATTERN above to match the new filename.
      2. Add the extractor to ARCHIVE_EXTRACTORS in lib.py if not already there.
    """
    log_section("FolderSync backup")

    result = pcloud_latest_file(PCLOUD_FOLDERSYNC_CODE, FOLDERSYNC_BACKUP_PATTERN)
    if result is None:
        log_error("Could not resolve FolderSync backup URL")
        return False

    url, filename = result
    archive_path = BACKUPS_DIR / filename

    if not download_file(url, archive_path):
        return False

    extracted = extract_archive(archive_path, BACKUPS_DIR)
    if extracted is None:
        log_error("FolderSync archive extraction failed")
        return False

    try:
        archive_path.unlink()
        log_info(f"Removed archive: {filename}")
    except OSError as exc:
        log_warn(f"Could not remove archive {filename}: {exc}")

    return True


def download_uadng() -> bool:
    """
    Download the UAD-NG Linux binary into tools/ and make it executable.
    This is a desktop tool — it is NOT pushed to the phone.
    Skip if the exact versioned filename already exists locally.
    """
    log_section("UAD-NG — desktop debloat tool (Linux binary)")

    result = github_asset_url(
        UADNG_REPO, UADNG_ASSET_PATTERN, exclude=UADNG_ASSET_EXCLUDE
    )
    if result is None:
        log_error("Could not resolve UAD-NG Linux binary URL")
        return False

    url, filename = result
    dest = TOOLS_DIR / filename

    if already_downloaded(dest):
        # Still ensure the executable bit is set in case it was lost
        _ensure_executable(dest)
        return True

    if not download_file(url, dest):
        return False

    _ensure_executable(dest)
    return True


def _ensure_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o755)
        log_ok(f"chmod +x: {path.name}")
    except OSError as exc:
        log_warn(f"Could not set executable bit on {path.name}: {exc}")


# ── Summary ───────────────────────────────────────────────────────────────────


def print_summary(results: dict[str, bool]) -> None:
    log_section("Download summary")
    all_ok = True
    for name, success in results.items():
        status = "\033[0;32m✓\033[0m" if success else "\033[0;31m✗\033[0m"
        print(f"  {status}  {name}")
        if not success:
            all_ok = False

    if all_ok:
        log_ok("All downloads completed successfully")
    else:
        log_error("One or more downloads failed — check output above")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    APKS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    tasks = {
        "shizuku": download_shizuku,
        "obtanium": download_obtanium,
        "obtanium-backup": download_obtanium_backup,
        "foldersync-backup": download_foldersync_backup,
        "uad-ng (desktop)": download_uadng,
    }

    results = {}
    for name, task in tasks.items():
        results[name] = task()

    print_summary(results)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
