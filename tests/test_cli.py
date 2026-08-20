from __future__ import annotations

from pathlib import Path

import pytest

from android_setup.cli import main
from android_setup.providers import SearchResult


def test_profile_commands(project_root: Path, capsys: object) -> None:
    root = str(project_root)
    assert main(["--root", root, "profiles", "list"]) == 0
    assert main(["--root", root, "profiles", "add", "new-phone"]) == 0
    assert main(["--root", root, "profiles", "show", "new-phone"]) == 0
    assert main(["--root", root, "profiles", "validate", "new-phone"]) == 0
    assert main(["--root", root, "profiles", "remove", "new-phone", "--yes"]) == 0


def test_apps_list_and_required_remove_guard(
    project_root: Path, capsys: object
) -> None:
    root = str(project_root)
    assert main(["--root", root, "apps", "list", "work"]) == 0
    output = capsys.readouterr().out
    assert "obtainium\tdev.imranr.obtainium\trequired" in output
    assert main(["--root", root, "apps", "remove", "work", "brave"]) == 2
    assert "required app cannot be removed" in capsys.readouterr().err


def test_https_file_add_list_remove(project_root: Path, capsys: object) -> None:
    root = str(project_root)
    add = [
        "--root",
        root,
        "files",
        "add",
        "work",
        "--provider",
        "https",
        "--id",
        "policy",
        "--name",
        "Policy",
        "--destination",
        "/sdcard/Work",
        "--type",
        "json",
        "--url",
        "https://example.test/policy.json",
    ]
    assert main(add) == 0
    assert main(["--root", root, "files", "list", "work"]) == 0
    assert "policy\thttps\t/sdcard/Work" in capsys.readouterr().out
    assert main(["--root", root, "files", "remove", "work", "policy"]) == 0


def test_missing_profile_returns_user_facing_error(
    project_root: Path, capsys: object
) -> None:
    assert main(["--root", str(project_root), "profiles", "show", "missing"]) == 2
    assert "profile not found" in capsys.readouterr().err


def test_profile_remove_cancel_and_edit(
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = str(project_root)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert main(["--root", root, "profiles", "remove", "work"]) == 1
    assert (project_root / "profiles" / "work.json").exists()
    monkeypatch.setattr("android_setup.store.ProfileStore.edit", lambda *_args: None)
    assert main(["--root", root, "profiles", "edit", "work"]) == 0


def test_app_search_add_and_remove(
    project_root: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = str(project_root)
    monkeypatch.setattr(
        "android_setup.providers.ProviderRegistry.search",
        lambda *_args: [SearchResult("fdroid", "Aegis", "com.aegis", "https://x")],
    )
    assert main(["--root", root, "apps", "search", "aegis"]) == 0
    assert "Aegis\tcom.aegis" in capsys.readouterr().out
    monkeypatch.setattr(
        "android_setup.providers.ProviderRegistry.fdroid_app",
        lambda *_args: ("Aegis", "com.aegis"),
    )
    assert (
        main(
            [
                "--root",
                root,
                "apps",
                "add",
                "work",
                "--provider",
                "fdroid",
                "--id",
                "aegis",
                "--package-id",
                "com.aegis",
            ]
        )
        == 0
    )
    assert main(["--root", root, "apps", "remove", "work", "aegis"]) == 0
    assert main(["--root", root, "apps", "remove", "work", "missing"]) == 2


def test_apkmirror_and_file_argument_guards(project_root: Path) -> None:
    root = str(project_root)
    base = [
        "--root",
        root,
        "apps",
        "add",
        "work",
        "--provider",
        "apkmirror",
        "--id",
        "signal",
        "--package-id",
        "org.signal",
    ]
    assert main(base) == 2
    assert main([*base, "--url", "https://example.test/app.apks"]) == 2
    assert main([*base, "--url", "https://example.test/app.apk"]) == 0
    assert (
        main(
            [
                "--root",
                root,
                "files",
                "add",
                "business",
                "--provider",
                "https",
                "--id",
                "x",
                "--name",
                "X",
                "--destination",
                "/sdcard/X",
            ]
        )
        == 2
    )
    pcloud = [
        "--root",
        root,
        "files",
        "add",
        "business",
        "--provider",
        "pcloud",
        "--id",
        "x",
        "--name",
        "X",
        "--destination",
        "/sdcard/X",
    ]
    assert main(pcloud) == 2
    assert main([*pcloud, "--pattern", "x", "--secret-ref", "folder"]) == 0
    assert main(["--root", root, "files", "remove", "business", "missing"]) == 2
