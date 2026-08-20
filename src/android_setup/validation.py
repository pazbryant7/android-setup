from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import zipfile
from pathlib import Path

from android_setup.errors import ValidationError
from android_setup.models import AppSpec, FileSpec


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_app(
    path: Path,
    app: AppSpec,
    expected_sha256: str | None = None,
    *,
    require_android_tools: bool = True,
) -> str:
    _validate_nonempty(path)
    _validate_checksum(path, expected_sha256)
    try:
        with zipfile.ZipFile(path) as archive:
            if (
                archive.testzip() is not None
                or "AndroidManifest.xml" not in archive.namelist()
            ):
                raise ValidationError(f"invalid APK ZIP structure: {path.name}")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValidationError(f"invalid APK: {path.name}: {exc}") from exc

    aapt = shutil.which("aapt")
    apksigner = shutil.which("apksigner")
    if require_android_tools and (not aapt or not apksigner):
        raise ValidationError("aapt and apksigner are required for APK validation")
    if aapt:
        badging = _run([aapt, "dump", "badging", str(path)])
        if f"package: name='{app.package_id}'" not in badging:
            raise ValidationError(
                f"{app.name} package mismatch; expected {app.package_id}"
            )
        native_lines = [
            line for line in badging.splitlines() if line.startswith("native-code:")
        ]
        if native_lines and f"'{app.architecture}'" not in native_lines[0]:
            raise ValidationError(
                f"{app.name} does not support required architecture {app.architecture}"
            )
    if apksigner:
        output = _run([apksigner, "verify", "--print-certs", str(path)])
        if app.certificate_sha256:
            normalized = output.replace(":", "").lower()
            if app.certificate_sha256 not in normalized:
                raise ValidationError(f"{app.name} signing certificate mismatch")
    return sha256_file(path)


def validate_file(
    path: Path, spec: FileSpec, expected_sha256: str | None = None
) -> str:
    _validate_nonempty(path)
    _validate_checksum(path, expected_sha256 or spec.sha256)
    if spec.file_type == "json":
        try:
            with path.open(encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, (dict, list)):
                raise ValidationError(
                    f"JSON root must be an object or list: {path.name}"
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"invalid JSON file {path.name}: {exc}") from exc
    elif spec.file_type == "sqlite":
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
            if result != ("ok",):
                raise ValidationError(f"SQLite integrity check failed: {path.name}")
        except sqlite3.Error as exc:
            raise ValidationError(
                f"invalid SQLite database {path.name}: {exc}"
            ) from exc
    elif spec.file_type == "zip":
        try:
            with zipfile.ZipFile(path) as archive:
                broken = archive.testzip()
                if broken:
                    raise ValidationError(f"corrupt ZIP member {broken}: {path.name}")
        except zipfile.BadZipFile as exc:
            raise ValidationError(f"invalid ZIP file {path.name}") from exc
    elif spec.file_type == "text":
        try:
            path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValidationError(
                f"invalid UTF-8 text file {path.name}: {exc}"
            ) from exc
    return sha256_file(path)


def _validate_nonempty(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValidationError(f"file is missing or empty: {path}")


def _validate_checksum(path: Path, expected: str | None) -> None:
    if expected and sha256_file(path).lower() != expected.lower():
        raise ValidationError(f"SHA-256 mismatch: {path.name}")


def _run(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValidationError(f"validation command failed: {detail}")
    return result.stdout
