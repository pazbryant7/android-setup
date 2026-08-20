from __future__ import annotations

import pytest

from android_setup.errors import ConfigError
from android_setup.models import AppSpec, BaseProfile, FileSpec, Profile


def test_profile_parses_and_combines_required_apps() -> None:
    base = BaseProfile.from_dict(
        {
            "schema_version": 1,
            "required_apps": [_app("required", "example.required")],
        }
    )
    profile = Profile.from_dict(
        {
            "schema_version": 1,
            "name": "phone-one",
            "description": "test",
            "apps": [_app("extra", "example.extra")],
            "directories": ["/sdcard/Test"],
            "files": [],
            "instructions": ["Done"],
        }
    )
    assert [app.id for app in profile.effective_apps(base)] == ["required", "extra"]
    assert profile.to_dict()["directories"] == ["/sdcard/Test"]


@pytest.mark.parametrize("name", ["../bad", "Upper", "two words", ""])
def test_profile_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ConfigError, match="lowercase slug|non-empty string"):
        Profile.from_dict({"schema_version": 1, "name": name})


@pytest.mark.parametrize("path", ["relative", "/sdcard/../data"])
def test_profile_rejects_unsafe_android_paths(path: str) -> None:
    data = {"schema_version": 1, "name": "safe", "directories": [path]}
    with pytest.raises(ConfigError, match="unsafe Android directory"):
        Profile.from_dict(data)


def test_duplicate_required_and_profile_app_is_rejected() -> None:
    base = BaseProfile.from_dict(
        {"schema_version": 1, "required_apps": [_app("same", "one.same")]}
    )
    profile = Profile.from_dict(
        {"schema_version": 1, "name": "safe", "apps": [_app("same", "two.same")]}
    )
    with pytest.raises(ConfigError, match="duplicate effective app ids"):
        profile.effective_apps(base)


def test_app_certificate_and_provider_validation() -> None:
    data = _app("sample", "example.sample")
    data["certificate_sha256"] = "bad"
    with pytest.raises(ConfigError, match="SHA-256"):
        AppSpec.from_dict(data)
    data = _app("sample", "example.sample")
    data["source"] = {"provider": "unknown"}
    with pytest.raises(ConfigError, match="provider"):
        AppSpec.from_dict(data)


def test_file_extract_configuration_round_trip() -> None:
    item = FileSpec.from_dict(
        {
            "id": "backup",
            "name": "Backup",
            "destination": "/sdcard/Download",
            "type": "zip",
            "extract_member": "*.db",
            "extract_type": "sqlite",
            "source": {"provider": "https", "url": "https://example.test/a.zip"},
        }
    )
    assert item.to_dict()["extract_type"] == "sqlite"


def test_file_rejects_invalid_hash_and_extract_type() -> None:
    data = {
        "id": "backup",
        "name": "Backup",
        "destination": "/sdcard/Download",
        "type": "json",
        "sha256": "bad",
        "source": {"provider": "https", "url": "https://example.test/a"},
    }
    with pytest.raises(ConfigError, match="SHA-256"):
        FileSpec.from_dict(data)
    data.pop("sha256")
    data["extract_member"] = "*.db"
    with pytest.raises(ConfigError, match="requires type 'zip'"):
        FileSpec.from_dict(data)


def _app(app_id: str, package_id: str) -> dict[str, object]:
    return {
        "id": app_id,
        "name": app_id.title(),
        "package_id": package_id,
        "source": {"provider": "https", "url": f"https://example.test/{app_id}.apk"},
    }
