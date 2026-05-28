#!/usr/bin/env python3
"""
download.py — fetch latest APKs from GitHub and backups from pCloud.

Run from repo root:
    python3 scripts/download.py

All files are saved under their original upstream names:
    apks/   shizuku-v<version>-release.apk
            app-arm64-v8a-release.apk
    backups/ obtainium-export-<timestamp>-auto.json
             <date> - foldersync.db.zip
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib import (
    download_file,
    github_asset_url,
    log_error,
    log_ok,
    log_section,
    log_warn,
    pcloud_latest_file,
)

# ── Config ────────────────────────────────────────────────────────────────────

APKS_DIR = REPO_ROOT / "apks"
BACKUPS_DIR = REPO_ROOT / "backups"

SHIZUKU_REPO = "RikkaApps/Shizuku"
SHIZUKU_APK_PATTERN = "shizuku-"  # matches shizuku-v13.x.x...-release.apk
SHIZUKU_APK_EXCLUDE = ""

OBTANIUM_REPO = "ImranR98/Obtainium"
OBTANIUM_APK_PATTERN = "app-arm64-v8a-release.apk"
OBTANIUM_APK_EXCLUDE = "fdroid"
OBTANIUM_APK_FALLBACK = "app-release.apk"

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
    return download_file(url, APKS_DIR / filename)


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
    return download_file(url, APKS_DIR / filename)


def download_obtanium_backup() -> bool:
    log_section("Obtanium backup")

    result = pcloud_latest_file(PCLOUD_OBTANIUM_CODE, OBTANIUM_BACKUP_PATTERN)
    if result is None:
        log_error("Could not resolve Obtanium backup URL")
        return False

    url, filename = result
    return download_file(url, BACKUPS_DIR / filename)


def download_foldersync_backup() -> bool:
    log_section("FolderSync backup")

    result = pcloud_latest_file(PCLOUD_FOLDERSYNC_CODE, FOLDERSYNC_BACKUP_PATTERN)
    if result is None:
        log_error("Could not resolve FolderSync backup URL")
        return False

    url, filename = result
    return download_file(url, BACKUPS_DIR / filename)


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

    tasks = {
        "shizuku": download_shizuku,
        "obtanium": download_obtanium,
        "obtanium-backup": download_obtanium_backup,
        "foldersync-backup": download_foldersync_backup,
    }

    results = {}
    for name, task in tasks.items():
        results[name] = task()

    print_summary(results)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
