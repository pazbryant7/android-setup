from __future__ import annotations

import hashlib
import http.server
import sqlite3
import threading
import urllib.error
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import make_apk

from android_setup.artifacts import ArtifactManager
from android_setup.errors import ValidationError
from android_setup.models import BaseProfile, Profile
from android_setup.providers import ResolvedArtifact


@pytest.mark.integration
def test_local_download_manifest_isolation_and_verification(tmp_path: Path) -> None:
    served = tmp_path / "served"
    make_apk(served / "sample.apk", "example.sample")
    (served / "config.json").write_text('{"enabled": true}', encoding="utf-8")
    with local_server(served) as base_url:
        base = BaseProfile.from_dict(
            {
                "schema_version": 1,
                "required_apps": [
                    {
                        "id": "sample",
                        "name": "Sample",
                        "package_id": "example.sample",
                        "source": {
                            "provider": "https",
                            "url": f"{base_url}/sample.apk",
                        },
                    }
                ],
            }
        )
        first = _profile("first", f"{base_url}/config.json")
        second = _profile("second", f"{base_url}/config.json")
        manager = ArtifactManager(tmp_path, require_android_tools=False)
        first_records = manager.download(first, base, {})
        manager.download(second, base, {})
        assert len(first_records) == 2
        assert (tmp_path / "artifacts" / "first" / "manifest.json").is_file()
        assert (tmp_path / "artifacts" / "second" / "manifest.json").is_file()
        assert len(manager.verify(first, base)) == 2


@pytest.mark.integration
def test_corrupt_redownload_preserves_previous_valid_artifact(tmp_path: Path) -> None:
    served = tmp_path / "served"
    make_apk(served / "sample.apk", "example.sample")
    with local_server(served) as base_url:
        base = BaseProfile.from_dict(
            {
                "schema_version": 1,
                "required_apps": [
                    {
                        "id": "sample",
                        "name": "Sample",
                        "package_id": "example.sample",
                        "source": {
                            "provider": "https",
                            "url": f"{base_url}/sample.apk",
                        },
                    }
                ],
            }
        )
        profile = Profile.from_dict({"schema_version": 1, "name": "phone"})
        manager = ArtifactManager(tmp_path, require_android_tools=False)
        manager.download(profile, base, {})
        cached = tmp_path / "artifacts" / "phone" / "apks" / "sample.apk"
        original_hash = hashlib.sha256(cached.read_bytes()).hexdigest()
        (served / "sample.apk").write_bytes(b"corrupt")
        with pytest.raises(ValidationError, match="invalid APK"):
            manager.download(profile, base, {})
        assert hashlib.sha256(cached.read_bytes()).hexdigest() == original_hash


@pytest.mark.integration
def test_zip_member_is_extracted_and_sqlite_checked(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    database = tmp_path / "foldersync.db"
    with sqlite3.connect(database) as connection:
        connection.execute("create table sync_pairs (name text)")
    with zipfile.ZipFile(served / "backup.zip", "w") as archive:
        archive.write(database, "nested/foldersync.db")
    with local_server(served) as base_url:
        base = BaseProfile.from_dict({"schema_version": 1, "required_apps": []})
        profile = Profile.from_dict(
            {
                "schema_version": 1,
                "name": "phone",
                "files": [
                    {
                        "id": "foldersync",
                        "name": "FolderSync",
                        "type": "zip",
                        "extract_member": "*.db",
                        "extract_type": "sqlite",
                        "destination": "/sdcard/Download",
                        "source": {
                            "provider": "https",
                            "url": f"{base_url}/backup.zip",
                        },
                    }
                ],
            }
        )
        manager = ArtifactManager(tmp_path, require_android_tools=False)
        record = manager.download(profile, base, {})[0]
        assert record.path.endswith("foldersync.db")
        assert not (tmp_path / "artifacts" / "phone" / "files" / "backup.zip").exists()


@pytest.mark.integration
def test_download_retries_transient_network_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0

    class Response:
        reads = 0

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            self.reads += 1
            return b"content" if self.reads == 1 else b""

    def urlopen(*_args: object, **_kwargs: object) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise urllib.error.URLError("temporary")
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    manager = ArtifactManager(tmp_path, download_retries=3)
    result = manager._download_to_temporary(
        ResolvedArtifact("https://example.test/file", "file"), tmp_path / "out"
    )
    assert attempts == 3
    assert result.read_bytes() == b"content"


def _profile(name: str, url: str) -> Profile:
    return Profile.from_dict(
        {
            "schema_version": 1,
            "name": name,
            "files": [
                {
                    "id": "config",
                    "name": "Config",
                    "type": "json",
                    "destination": "/sdcard/Download",
                    "source": {"provider": "https", "url": url},
                }
            ],
        }
    )


@contextmanager
def local_server(directory: Path) -> Iterator[str]:
    def handler(
        *args: object, **kwargs: object
    ) -> http.server.SimpleHTTPRequestHandler:
        return http.server.SimpleHTTPRequestHandler(
            *args, directory=str(directory), **kwargs
        )

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
