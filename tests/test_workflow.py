from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import make_apk

from android_setup.cli import main
from android_setup.models import Profile
from android_setup.store import ProfileStore
from android_setup.validation import sha256_file


@pytest.mark.workflow
@pytest.mark.parametrize(
    ("profile_name", "expected_apps", "expect_personal_data"),
    [("personal", 4, True), ("work", 3, False), ("business", 3, False)],
)
def test_complete_recorded_adb_workflow(
    project_root: Path,
    tmp_path: Path,
    fake_android_tools: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_name: str,
    expected_apps: int,
    expect_personal_data: bool,
) -> None:
    store = ProfileStore(project_root)
    profile = store.load(profile_name)
    _write_verified_artifacts(
        project_root, profile, store, include_files=expect_personal_data
    )
    log = tmp_path / f"{profile_name}-adb.log"
    adb = _fake_adb(tmp_path, log)
    monkeypatch.setenv("FAKE_ADB_LOG", str(log))
    exit_code = main(
        [
            "--root",
            str(project_root),
            "setup",
            profile_name,
            "--adb",
            str(adb),
            "--device",
            "serial-one",
            "--non-interactive",
            "--skip-download",
        ]
    )
    assert exit_code == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert sum(" install -r " in f" {line} " for line in lines) == expected_apps
    pushes = [line for line in lines if " push " in f" {line} "]
    if expect_personal_data:
        assert len(pushes) == 2
        assert any("obtainium-backup.json" in line for line in pushes)
        assert any("foldersync-backup.db" in line for line in pushes)
        assert any("mkdir -p /sdcard/Mihon/autobackup" in line for line in lines)
    else:
        assert pushes == []
        assert not any("/sdcard/Mihon" in line for line in lines)


def _write_verified_artifacts(
    root: Path, profile: Profile, store: ProfileStore, *, include_files: bool
) -> None:
    target = root / "artifacts" / profile.name
    entries: list[dict[str, object]] = []
    for app in profile.effective_apps(store.load_base()):
        path = target / "apks" / f"{app.id}.apk"
        make_apk(path, app.package_id)
        entries.append(_entry("app", app.id, app.name, path.relative_to(target), path))
    if include_files:
        json_path = target / "files" / "obtainium-backup.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text('{"apps": []}', encoding="utf-8")
        entries.append(
            _entry(
                "file",
                "obtainium-backup",
                "Obtainium backup",
                json_path.relative_to(target),
                json_path,
            )
        )
        db_path = target / "files" / "foldersync-backup.db"
        import sqlite3

        with sqlite3.connect(db_path) as database:
            database.execute("create table pairs (name text)")
        entries.append(
            _entry(
                "file",
                "foldersync-backup",
                "FolderSync backup",
                db_path.relative_to(target),
                db_path,
            )
        )
    target.mkdir(parents=True, exist_ok=True)
    (target / "manifest.json").write_text(
        json.dumps(
            {"schema_version": 1, "profile": profile.name, "artifacts": entries},
            indent=2,
        ),
        encoding="utf-8",
    )


def _entry(
    kind: str, item_id: str, name: str, relative: Path, path: Path
) -> dict[str, object]:
    return {
        "kind": kind,
        "id": item_id,
        "name": name,
        "path": str(relative),
        "source_url": "https://fixture.invalid/artifact",
        "sha256": sha256_file(path),
        "version": "test",
        "downloaded_at": datetime.now(UTC).isoformat(),
    }


def _fake_adb(directory: Path, log: Path) -> Path:
    executable = directory / "fake-adb"
    executable.write_text(
        """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if args == ['devices', '-l']:
    print('List of devices attached')
    print('serial-one device product:fixture model:Test_Phone device:fixture')
    raise SystemExit(0)
with open(os.environ['FAKE_ADB_LOG'], 'a', encoding='utf-8') as handle:
    handle.write(' '.join(args) + '\\n')
print('Success')
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable
