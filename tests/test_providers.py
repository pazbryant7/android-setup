from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from android_setup.errors import ConfigError, ProviderError
from android_setup.models import SourceSpec
from android_setup.providers import HttpClient, ProviderRegistry


class FakeClient:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses

    def json(self, url: str) -> Any:
        return self.responses[url]

    def get(self, url: str) -> bytes:
        value = self.responses[url]
        return value if isinstance(value, bytes) else json.dumps(value).encode()


def test_github_resolves_matching_release_asset() -> None:
    url = "https://api.github.com/repos/owner/repo/releases/latest"
    registry = ProviderRegistry(
        FakeClient(
            {
                url: {
                    "tag_name": "v1",
                    "assets": [
                        {
                            "name": "app-fdroid.apk",
                            "browser_download_url": "https://x/f.apk",
                        },
                        {
                            "name": "app-release.apk",
                            "browser_download_url": "https://x/app.apk",
                        },
                    ],
                }
            }
        )
    )
    result = registry.resolve(
        SourceSpec(
            "github",
            {"repo": "owner/repo", "asset_pattern": "app", "exclude": "fdroid"},
        ),
        {},
    )
    assert result.filename == "app-release.apk"
    assert result.version == "v1"


def test_fdroid_selects_highest_version_and_hash() -> None:
    url = "https://repo.test/index-v1.json"
    registry = ProviderRegistry(
        FakeClient(
            {
                url: {
                    "packages": {
                        "example.app": [
                            {"apkName": "old.apk", "versionCode": 1, "hash": "aa"},
                            {
                                "apkName": "new.apk",
                                "versionCode": 2,
                                "versionName": "2",
                                "hash": "bb",
                            },
                        ]
                    }
                }
            }
        )
    )
    result = registry.resolve(
        SourceSpec(
            "fdroid", {"repo_url": "https://repo.test", "package_id": "example.app"}
        ),
        {},
    )
    assert result.filename == "new.apk"
    assert result.sha256 == "bb"


def test_html_https_and_secret_resolution() -> None:
    page = "https://example.test/files/"
    registry = ProviderRegistry(
        FakeClient({page: b'<a href="MiXplorer_v2.apk">latest</a>'})
    )
    result = registry.resolve(
        SourceSpec("html", {"page_url": page, "asset_pattern": "MiXplorer_"}), {}
    )
    assert result.url == "https://example.test/files/MiXplorer_v2.apk"
    direct = registry.resolve(
        SourceSpec(
            "https",
            {"secret_ref": "url", "secret_field": "url", "filename": "private.json"},
        ),
        {"url": "https://example.test/private"},
    )
    assert direct.filename == "private.json"
    with pytest.raises(ConfigError, match="missing secret"):
        registry.resolve(
            SourceSpec(
                "https",
                {"secret_ref": "missing", "secret_field": "url", "filename": "x"},
            ),
            {},
        )


def test_pcloud_resolves_latest_matching_file() -> None:
    list_url = "https://api.pcloud.com/showpublink?code=secret"
    get_url = "https://api.pcloud.com/getpublinkdownload?code=secret&fileid=2"
    registry = ProviderRegistry(
        FakeClient(
            {
                list_url: {
                    "result": 0,
                    "metadata": {
                        "contents": [
                            {"name": "backup-1.json", "fileid": 1},
                            {"name": "backup-2.json", "fileid": 2},
                        ]
                    },
                },
                get_url: {"hosts": ["download.test"], "path": "/backup"},
            }
        )
    )
    result = registry.resolve(
        SourceSpec("pcloud", {"folder_code": "secret", "pattern": "backup"}), {}
    )
    assert result.filename == "backup-2.json"
    assert result.url == "https://download.test/backup"


def test_provider_errors_are_actionable() -> None:
    registry = ProviderRegistry(
        FakeClient({"https://repo.test/index-v1.json": {"packages": {}}})
    )
    with pytest.raises(ProviderError, match="not found"):
        registry.resolve(
            SourceSpec(
                "fdroid", {"repo_url": "https://repo.test", "package_id": "missing"}
            ),
            {},
        )
    with pytest.raises(ProviderError, match="HTTPS"):
        registry.resolve(SourceSpec("https", {"url": "http://example.com/a.apk"}), {})


def test_search_providers_and_fdroid_selection() -> None:
    fdroid_url = "https://f-droid.org/api/v1/packages"
    mirror_url = (
        "https://www.apkmirror.com/?post_type=app_release&searchtype=apk&s=Signal"
    )
    registry = ProviderRegistry(
        FakeClient(
            {
                fdroid_url: [
                    "ignored",
                    {
                        "packageName": "org.example.other",
                        "name": "Other",
                        "summary": "No match",
                    },
                    {
                        "packageName": "org.signal.app",
                        "name": "Signal",
                        "summary": "Messenger",
                    },
                ],
                mirror_url: (
                    b'<a href="/apk/signal/release/"><b>Signal</b></a>'
                    b'<a href="/apk/signal/release/">duplicate</a>'
                    b'<a href="/apk/empty/"></a>'
                ),
            }
        )
    )
    fdroid = registry.search("signal", "fdroid")
    assert [item.identifier for item in fdroid] == ["org.signal.app"]
    assert registry.fdroid_app("org.signal.app") == ("Signal", "org.signal.app")
    mirror = registry.search("Signal", "apkmirror")
    assert len(mirror) == 1
    assert mirror[0].url.endswith("/apk/signal/release/")
    with pytest.raises(ProviderError, match="not found"):
        registry.fdroid_app("missing")
    with pytest.raises(ProviderError, match="search provider"):
        registry.search("x", "unknown")


@pytest.mark.parametrize(
    ("source", "responses", "message"),
    [
        (
            SourceSpec("github", {"repo": "o/r", "asset_pattern": "apk"}),
            {"https://api.github.com/repos/o/r/releases/latest": []},
            "unexpected GitHub",
        ),
        (
            SourceSpec("github", {"repo": "o/r", "asset_pattern": "apk"}),
            {"https://api.github.com/repos/o/r/releases/latest": {"assets": []}},
            "no GitHub asset",
        ),
        (
            SourceSpec("fdroid", {"repo_url": "https://r", "package_id": "app"}),
            {"https://r/index-v1.json": []},
            "unexpected F-Droid",
        ),
        (
            SourceSpec("fdroid", {"repo_url": "https://r", "package_id": "app"}),
            {"https://r/index-v1.json": {"packages": {"app": ["bad"]}}},
            "no APK builds",
        ),
        (
            SourceSpec("html", {"page_url": "https://page", "asset_pattern": "App"}),
            {"https://page": b"nothing"},
            "no APK matching",
        ),
        (
            SourceSpec("https", {"url": "https://example.test/"}),
            {},
            "requires a filename",
        ),
    ],
)
def test_resolution_error_paths(
    source: SourceSpec, responses: dict[str, Any], message: str
) -> None:
    with pytest.raises(ProviderError, match=message):
        ProviderRegistry(FakeClient(responses)).resolve(source, {})


def test_pcloud_error_paths() -> None:
    list_url = "https://api.pcloud.com/showpublink?code=x"
    source = SourceSpec("pcloud", {"folder_code": "x", "pattern": "backup"})
    with pytest.raises(ProviderError, match="lookup failed"):
        ProviderRegistry(FakeClient({list_url: {"result": 1}})).resolve(source, {})
    with pytest.raises(ProviderError, match="no pCloud file"):
        ProviderRegistry(
            FakeClient({list_url: {"result": 0, "metadata": {"contents": []}}})
        ).resolve(source, {})
    get_url = "https://api.pcloud.com/getpublinkdownload?code=x&fileid=1"
    with pytest.raises(ProviderError, match="download URL"):
        ProviderRegistry(
            FakeClient(
                {
                    list_url: {
                        "result": 0,
                        "metadata": {"contents": [{"name": "backup", "fileid": 1}]},
                    },
                    get_url: {},
                }
            )
        ).resolve(source, {})


def test_http_client_success_retry_and_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok": true}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: Response())
    assert HttpClient().json("https://example.test") == {"ok": True}

    def fail(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(ProviderError, match="request failed"):
        HttpClient(retries=2).get("https://example.test")
    client = HttpClient()
    monkeypatch.setattr(client, "get", lambda _url: b"bad-json")
    with pytest.raises(ProviderError, match="invalid JSON"):
        client.json("https://example.test")


def test_invalid_secret_shape_and_missing_provider_option() -> None:
    registry = ProviderRegistry(FakeClient({}))
    with pytest.raises(ConfigError, match="must be strings"):
        registry.resolve(
            SourceSpec("https", {"secret_ref": 1, "secret_field": "url"}), {}
        )
    with pytest.raises(ProviderError, match="required"):
        registry.resolve(SourceSpec("https", {}), {})
