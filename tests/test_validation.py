from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from conftest import make_apk

from android_setup.errors import ValidationError
from android_setup.models import AppSpec, FileSpec
from android_setup.validation import sha256_file, validate_app, validate_file


def test_apk_identity_signature_and_hash(
    tmp_path: Path, fake_android_tools: Path
) -> None:
    path = tmp_path / "app.apk"
    make_apk(path, "dev.imranr.obtainium")
    app = AppSpec.from_dict(
        {
            "id": "obtainium",
            "name": "Obtainium",
            "package_id": "dev.imranr.obtainium",
            "certificate_sha256": (
                "b353601f6a1d5fd6603ae2f50be80cf301367b86b6ab8b1f66243da96cd57362"
            ),
            "source": {"provider": "https", "url": "https://example.test/app.apk"},
        }
    )
    assert validate_app(path, app, sha256_file(path)) == sha256_file(path)
    wrong = AppSpec.from_dict({**app.to_dict(), "package_id": "wrong.package"})
    with pytest.raises(ValidationError, match="package mismatch"):
        validate_app(path, wrong)
    with pytest.raises(ValidationError, match="SHA-256 mismatch"):
        validate_app(path, app, "0" * 64)
    wrong_certificate = AppSpec.from_dict(
        {**app.to_dict(), "certificate_sha256": "0" * 64}
    )
    with pytest.raises(ValidationError, match="signing certificate mismatch"):
        validate_app(path, wrong_certificate)


def test_apk_requires_android_validation_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "app.apk"
    make_apk(path, "example.app")
    app = AppSpec.from_dict(
        {
            "id": "app",
            "name": "App",
            "package_id": "example.app",
            "source": {"provider": "https", "url": "https://example.test/app.apk"},
        }
    )
    monkeypatch.setattr("android_setup.validation.shutil.which", lambda _name: None)
    with pytest.raises(ValidationError, match="aapt and apksigner"):
        validate_app(path, app)


def test_json_text_zip_and_sqlite_validation(tmp_path: Path) -> None:
    json_path = tmp_path / "backup.json"
    json_path.write_text(json.dumps({"apps": []}), encoding="utf-8")
    assert validate_file(json_path, _file("json"))
    text_path = tmp_path / "config.txt"
    text_path.write_text("hello", encoding="utf-8")
    assert validate_file(text_path, _file("text"))
    zip_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("file.txt", "hello")
    assert validate_file(zip_path, _file("zip"))
    db_path = tmp_path / "backup.db"
    with sqlite3.connect(db_path) as database:
        database.execute("create table example (value text)")
    assert validate_file(db_path, _file("sqlite"))


@pytest.mark.parametrize(
    ("file_type", "content", "message"),
    [("json", b"not-json", "invalid JSON"), ("zip", b"not-zip", "invalid ZIP")],
)
def test_invalid_files_are_rejected(
    tmp_path: Path, file_type: str, content: bytes, message: str
) -> None:
    path = tmp_path / "bad"
    path.write_bytes(content)
    with pytest.raises(ValidationError, match=message):
        validate_file(path, _file(file_type))


def test_empty_and_scalar_json_files_are_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.touch()
    with pytest.raises(ValidationError, match="missing or empty"):
        validate_file(empty, _file("binary"))
    scalar = tmp_path / "scalar.json"
    scalar.write_text("1", encoding="utf-8")
    with pytest.raises(ValidationError, match="JSON root"):
        validate_file(scalar, _file("json"))


def _file(file_type: str) -> FileSpec:
    return FileSpec.from_dict(
        {
            "id": "sample",
            "name": "Sample",
            "destination": "/sdcard/Download",
            "type": file_type,
            "source": {"provider": "https", "url": "https://example.test/file"},
        }
    )
