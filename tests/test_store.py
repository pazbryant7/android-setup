from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from android_setup.errors import ConfigError
from android_setup.store import ProfileStore


def test_profile_crud_and_copy(project_root: Path) -> None:
    store = ProfileStore(project_root)
    created = store.add("new-phone")
    assert created.name == "new-phone"
    copied = store.add("personal-copy", "personal")
    assert copied.directories == store.load("personal").directories
    assert [item.name for item in store.list()] == [
        "business",
        "new-phone",
        "personal-copy",
        "personal",
        "work",
    ]
    store.remove("new-phone")
    with pytest.raises(ConfigError, match="not found"):
        store.load("new-phone")


def test_store_rejects_duplicate_and_filename_mismatch(project_root: Path) -> None:
    store = ProfileStore(project_root)
    with pytest.raises(ConfigError, match="already exists"):
        store.add("personal")
    path = project_root / "profiles" / "wrong.json"
    path.write_text('{"schema_version": 1, "name": "other"}', encoding="utf-8")
    with pytest.raises(ConfigError, match="filename and name differ"):
        store.load("wrong")


def test_secrets_are_optional_and_typed(project_root: Path) -> None:
    store = ProfileStore(project_root)
    assert store.secrets("work") == {}
    path = project_root / "profiles" / ".secrets" / "work.json"
    path.parent.mkdir()
    path.write_text('{"token": "value"}', encoding="utf-8")
    assert store.secrets("work") == {"token": "value"}
    path.write_text('{"token": 1}', encoding="utf-8")
    with pytest.raises(ConfigError, match="string values"):
        store.secrets("work")


def test_atomic_save_preserves_valid_json(project_root: Path) -> None:
    store = ProfileStore(project_root)
    profile = store.load("work")
    store.save(profile)
    data = json.loads((project_root / "profiles" / "work.json").read_text())
    assert data["name"] == "work"
    assert not list((project_root / "profiles").glob(".work.json.*"))


def test_edit_success_and_failures(
    project_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProfileStore(project_root)
    editor = tmp_path / "editor"
    editor.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "p=sys.argv[1]; d=json.load(open(p)); d['description']='edited'; "
        "json.dump(d, open(p, 'w'))\n",
        encoding="utf-8",
    )
    editor.chmod(editor.stat().st_mode | stat.S_IXUSR)
    assert store.edit("work", str(editor)).description == "edited"
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    with pytest.raises(ConfigError, match=r"set \$VISUAL"):
        store.edit("work")
    failing = tmp_path / "failing"
    failing.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    failing.chmod(failing.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ConfigError, match="status 7"):
        store.edit("work", str(failing))


def test_store_error_paths(project_root: Path, tmp_path: Path) -> None:
    store = ProfileStore(project_root)
    with pytest.raises(ConfigError, match="lowercase slug"):
        store.load("../unsafe")
    missing = ProfileStore(tmp_path / "missing")
    with pytest.raises(ConfigError, match="profiles directory"):
        missing.list()
    invalid = project_root / "profiles" / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="could not read JSON"):
        store.load("invalid")
