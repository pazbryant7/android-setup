"""
lib.py — shared utilities for android-setup scripts.

Covers: logging, file verification, retried downloads,
GitHub release asset resolution, pCloud public folder resolution,
archive extraction with a pluggable extractor registry.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── ANSI colours ──────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
DIM = "\033[2m"


# ── Logging ───────────────────────────────────────────────────────────────────


def log_info(msg: str) -> None:
    print(f"{BLUE}[INFO]{RESET}  {msg}")


def log_ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET}    {msg}")


def log_skip(msg: str) -> None:
    print(f"{DIM}[SKIP]  {msg}{RESET}")


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET}  {msg}")


def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{RESET} {msg}", file=sys.stderr)


def log_section(msg: str) -> None:
    print(f"\n{BOLD}==> {msg}{RESET}")


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _http_get(url: str, retries: int = 3, delay: float = 2.0) -> bytes | None:
    """
    Fetch a URL, returning raw bytes.
    Retries on network/HTTP errors up to `retries` times.
    Returns None on total failure (never raises).
    """
    headers = {"User-Agent": "android-setup/1.0"}
    attempt = 0
    while attempt < retries:
        attempt += 1
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            log_warn(f"Request failed (attempt {attempt}/{retries}): {exc}")
            if attempt < retries:
                time.sleep(delay)
    return None


def _http_get_json(url: str) -> dict | None:
    """Fetch a URL and parse response as JSON. Returns None on any failure."""
    raw = _http_get(url)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log_error(f"JSON parse error from {url}: {exc}")
        return None


# ── File helpers ──────────────────────────────────────────────────────────────


def verify_file(path: Path) -> bool:
    """Return True if file exists and is non-empty."""
    if not path.is_file() or path.stat().st_size == 0:
        log_error(f"File missing or empty: {path}")
        return False
    size_kb = path.stat().st_size // 1024
    log_ok(f"Verified: {path.name} ({size_kb} KB)")
    return True


def already_downloaded(dest: Path) -> bool:
    """
    Return True if `dest` already exists and is non-empty, logging a skip
    message.  Call this before download_file() to avoid redundant fetches.
    """
    if dest.is_file() and dest.stat().st_size > 0:
        size_kb = dest.stat().st_size // 1024
        log_skip(f"Already exists: {dest.name} ({size_kb} KB)")
        return True
    return False


def download_file(url: str, dest: Path, retries: int = 3) -> bool:
    """
    Download `url` to `dest` with progress indication.
    Returns True on success, False on failure.
    Does not raise.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "android-setup/1.0"}
    attempt = 0

    while attempt < retries:
        attempt += 1
        log_info(f"Downloading (attempt {attempt}/{retries}): {dest.name}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as fh:
                while chunk := resp.read(65536):
                    fh.write(chunk)
            if verify_file(dest):
                return True
            log_warn("Download completed but file is empty, retrying...")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            log_warn(f"Download failed (attempt {attempt}/{retries}): {exc}")

        if attempt < retries:
            time.sleep(2)

    log_error(f"Failed to download after {retries} attempts: {url}")
    return False


# ── Archive extraction ────────────────────────────────────────────────────────
#
# ARCHIVE_EXTRACTORS maps a suffix to a callable:
#
#   extractor(archive_path: Path, dest_dir: Path) -> list[Path]
#
# It must return a list of the top-level extracted paths, or raise on failure.
#
# To add a new format (e.g. RAR), install the required library and append:
#
#   import rarfile
#   def _extract_rar(archive: Path, dest: Path) -> list[Path]:
#       with rarfile.RarFile(archive) as rf:
#           rf.extractall(dest)
#           return [dest / n for n in rf.namelist()]
#   ARCHIVE_EXTRACTORS[".rar"] = _extract_rar
#
# Then update the relevant BACKUP_PATTERN in download.py to match the new name.
# ─────────────────────────────────────────────────────────────────────────────

import tarfile
import zipfile


def _extract_zip(archive: Path, dest: Path) -> list[Path]:
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
        return [dest / name for name in zf.namelist()]


def _extract_tar(archive: Path, dest: Path) -> list[Path]:
    with tarfile.open(archive) as tf:
        tf.extractall(dest)
        return [dest / m.name for m in tf.getmembers()]


# Registry: suffix → extractor callable.
# Add or override entries here to support more formats.
ARCHIVE_EXTRACTORS: dict[str, callable] = {
    ".zip": _extract_zip,
    ".tar": _extract_tar,
    ".tar.gz": _extract_tar,
    ".tgz": _extract_tar,
    ".tar.bz2": _extract_tar,
    ".tar.xz": _extract_tar,
    # ".rar": _extract_rar,   ← uncomment after: pip install rarfile
    # ".7z":  _extract_7z,    ← uncomment after: pip install py7zr
}


def _archive_suffix(path: Path) -> str | None:
    """
    Return the registered archive suffix for `path`, or None if unrecognised.
    Checks compound suffixes like '.tar.gz' before single ones.
    """
    name = path.name
    for suffix in ARCHIVE_EXTRACTORS:
        if name.endswith(suffix):
            return suffix
    return None


def extract_archive(archive: Path, dest_dir: Path) -> list[Path] | None:
    """
    Extract `archive` into `dest_dir` using the registered extractor for its
    format.  Returns the list of extracted paths on success, or None on failure.

    To support a new format add an entry to ARCHIVE_EXTRACTORS (see above).
    """
    suffix = _archive_suffix(archive)
    if suffix is None:
        log_error(
            f"No extractor registered for '{archive.suffix}'. "
            f"Add one to ARCHIVE_EXTRACTORS in lib.py. "
            f"Supported: {', '.join(ARCHIVE_EXTRACTORS)}"
        )
        return None

    extractor = ARCHIVE_EXTRACTORS[suffix]
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        paths = extractor(archive, dest_dir)
        log_ok(f"Extracted {archive.name} → {dest_dir} ({len(paths)} item(s))")
        return paths
    except Exception as exc:
        log_error(f"Failed to extract {archive.name}: {exc}")
        return None


# ── GitHub release helpers ────────────────────────────────────────────────────


def github_latest_release(repo: str) -> dict | None:
    """
    Fetch the latest release metadata for `owner/repo`.
    Returns the full release dict or None on failure.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_get_json(url)
    if data is None:
        log_error(f"Could not fetch release data for {repo}")
        return None
    if "tag_name" not in data:
        log_error(f"Unexpected GitHub response for {repo}: {list(data.keys())}")
        return None
    return data


def github_asset_url(
    repo: str, pattern: str, exclude: str = ""
) -> tuple[str, str] | None:
    """
    Return (browser_download_url, filename) of the first asset whose name
    contains `pattern` and does not contain `exclude` (if provided).
    Returns None on any failure.
    """
    release = github_latest_release(repo)
    if release is None:
        return None

    assets = release.get("assets", [])
    for asset in assets:
        name = asset.get("name", "")
        if pattern in name:
            if exclude and exclude in name:
                continue
            url = asset.get("browser_download_url")
            log_info(f"Resolved asset: {name}")
            return url, name

    log_error(f"No asset matching '{pattern}' (exclude='{exclude}') in {repo}")
    return None


# ── pCloud public folder helpers ──────────────────────────────────────────────


def _pcloud_list_folder(folder_code: str) -> dict | None:
    """Fetch pCloud public folder listing. Returns parsed JSON or None."""
    url = f"https://api.pcloud.com/showpublink?code={folder_code}"
    data = _http_get_json(url)
    if data is None:
        log_error(f"Could not list pCloud folder: {folder_code}")
        return None
    if data.get("result", 1) != 0:
        log_error(f"pCloud API error: {data.get('error', 'unknown')}")
        return None
    return data


def _pcloud_download_url(folder_code: str, fileid: int) -> str | None:
    """
    Resolve a direct download URL for a pCloud file by its fileid.
    Returns URL string or None on failure.
    """
    url = (
        f"https://api.pcloud.com/getpublinkdownload?code={folder_code}&fileid={fileid}"
    )
    data = _http_get_json(url)
    if data is None:
        return None

    hosts = data.get("hosts", [])
    path = data.get("path", "")

    if not hosts or not path:
        log_error(f"pCloud download URL missing hosts or path for fileid {fileid}")
        return None

    return f"https://{hosts[0]}{path}"


def pcloud_latest_file(folder_code: str, pattern: str) -> tuple[str, str] | None:
    """
    Find the most recent file in a pCloud public folder whose name contains
    `pattern`. Files are sorted lexicographically by name — date-prefixed
    filenames (YYYY-MM-DD or ISO timestamps) sort correctly this way.

    Returns (direct_download_url, original_filename), or None on failure.
    """
    listing = _pcloud_list_folder(folder_code)
    if listing is None:
        return None

    contents = listing.get("metadata", {}).get("contents", [])
    if not contents:
        log_error(f"pCloud folder is empty (code={folder_code})")
        return None

    matches = [f for f in contents if pattern in f.get("name", "")]
    if not matches:
        log_error(
            f"No files matching '{pattern}' in pCloud folder (code={folder_code})"
        )
        return None

    # Latest by lexicographic sort on name (date-prefixed names sort chronologically)
    latest = sorted(matches, key=lambda f: f["name"])[-1]
    filename = latest["name"]
    fileid = latest["fileid"]

    log_info(f"Latest match for '{pattern}': {filename}")

    url = _pcloud_download_url(folder_code, fileid)
    if url is None:
        return None

    return url, filename
