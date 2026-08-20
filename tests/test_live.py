from __future__ import annotations

import os
from pathlib import Path

import pytest

from android_setup.artifacts import ArtifactManager
from android_setup.models import Profile
from android_setup.store import ProfileStore

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("ANDROID_SETUP_LIVE") != "1",
        reason="set ANDROID_SETUP_LIVE=1 to use public providers",
    ),
]


def test_required_apps_resolve_download_and_validate(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    store = ProfileStore(repository)
    base = store.load_base()
    profile = Profile(1, "live", "Live provider validation", (), (), (), ())
    records = ArtifactManager(tmp_path).download(profile, base, {})
    assert {record.id for record in records} == {"obtainium", "brave", "mixplorer"}
