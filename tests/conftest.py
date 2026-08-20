from __future__ import annotations

import json
import os
import shutil
import stat
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1] / "profiles"
    shutil.copytree(
        source, tmp_path / "profiles", ignore=shutil.ignore_patterns(".secrets")
    )
    return tmp_path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_apk(path: Path, package_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"binary manifest")
        archive.writestr("package.txt", package_id)


@pytest.fixture
def fake_android_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tools = tmp_path / "tools"
    tools.mkdir()
    aapt = tools / "aapt"
    aapt.write_text(
        """#!/usr/bin/env python3
import sys, zipfile
with zipfile.ZipFile(sys.argv[-1]) as archive:
    package = archive.read('package.txt').decode()
print(f\"package: name='{package}' versionCode='1' versionName='1.0'\")
print(\"sdkVersion:'26'\")
print(\"native-code: 'arm64-v8a'\")
""",
        encoding="utf-8",
    )
    apksigner = tools / "apksigner"
    apksigner.write_text(
        """#!/usr/bin/env python3
print('Verifies')
digest = 'b353601f6a1d5fd6603ae2f50be80cf301367b86b6ab8b1f66243da96cd57362'
print(f'Signer #1 certificate SHA-256 digest: {digest}')
mix = '724eebd26a756e0762c255052e49709391baa21d17d98c34071e091f18b90063'
print(f'Fixture alternate certificate SHA-256 digest: {mix}')
""",
        encoding="utf-8",
    )
    for executable in (aapt, apksigner):
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ.get('PATH', '')}")
    return tools
