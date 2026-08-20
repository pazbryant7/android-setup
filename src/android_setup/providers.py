from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, cast

from android_setup.errors import ConfigError, ProviderError
from android_setup.models import SourceSpec

USER_AGENT = "android-setup/0.1"


@dataclass(frozen=True)
class ResolvedArtifact:
    url: str
    filename: str
    version: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class SearchResult:
    provider: str
    name: str
    identifier: str
    url: str
    summary: str = ""


class HttpClient:
    def __init__(self, timeout: float = 30.0, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = retries

    def get(self, url: str) -> bytes:
        last_error: Exception | None = None
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for _attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return cast(bytes, response.read())
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last_error = exc
        raise ProviderError(f"request failed for {url}: {last_error}")

    def json(self, url: str) -> Any:
        try:
            return json.loads(self.get(url))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"invalid JSON from {url}: {exc}") from exc


class ProviderRegistry:
    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def resolve(self, source: SourceSpec, secrets: dict[str, str]) -> ResolvedArtifact:
        options = self._resolve_secrets(source.options, secrets)
        if source.provider == "github":
            return self._github(options)
        if source.provider == "fdroid":
            return self._fdroid(options)
        if source.provider == "html":
            return self._html(options)
        if source.provider == "https":
            return self._https(options)
        if source.provider == "pcloud":
            return self._pcloud(options)
        raise ProviderError(f"unsupported provider: {source.provider}")

    def search(self, query: str, provider: str) -> list[SearchResult]:
        if provider == "fdroid":
            return self._search_fdroid(query)
        if provider == "apkmirror":
            return self._search_apkmirror(query)
        raise ProviderError("search provider must be fdroid or apkmirror")

    def fdroid_app(self, package_id: str) -> tuple[str, str]:
        results = self._search_fdroid(package_id)
        exact = [item for item in results if item.identifier == package_id]
        if not exact:
            raise ProviderError(f"F-Droid package not found: {package_id}")
        return exact[0].name, exact[0].identifier

    def _github(self, options: dict[str, Any]) -> ResolvedArtifact:
        repo = _required(options, "repo")
        pattern = _required(options, "asset_pattern")
        exclude = str(options.get("exclude", ""))
        data = self.client.json(f"https://api.github.com/repos/{repo}/releases/latest")
        if not isinstance(data, dict):
            raise ProviderError(f"unexpected GitHub response for {repo}")
        for asset in data.get("assets", []):
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", ""))
            if pattern in name and (not exclude or exclude not in name):
                url = str(asset.get("browser_download_url", ""))
                if not url:
                    continue
                return ResolvedArtifact(
                    url, name, str(data.get("tag_name", "")) or None
                )
        raise ProviderError(f"no GitHub asset matching {pattern!r} in {repo}")

    def _fdroid(self, options: dict[str, Any]) -> ResolvedArtifact:
        repo_url = _required(options, "repo_url").rstrip("/")
        package_id = _required(options, "package_id")
        index = self.client.json(f"{repo_url}/index-v1.json")
        if not isinstance(index, dict):
            raise ProviderError(f"unexpected F-Droid index from {repo_url}")
        packages = index.get("packages", {})
        builds = packages.get(package_id, []) if isinstance(packages, dict) else []
        if not isinstance(builds, list) or not builds:
            raise ProviderError(f"package {package_id} not found in {repo_url}")
        valid = [
            item for item in builds if isinstance(item, dict) and item.get("apkName")
        ]
        if not valid:
            raise ProviderError(f"package {package_id} has no APK builds")
        latest = max(valid, key=lambda item: int(item.get("versionCode", 0)))
        filename = str(latest["apkName"])
        digest = str(latest.get("hash", "")) or None
        return ResolvedArtifact(
            f"{repo_url}/{urllib.parse.quote(filename)}",
            filename,
            str(latest.get("versionName", "")) or None,
            digest.lower() if digest else None,
        )

    def _html(self, options: dict[str, Any]) -> ResolvedArtifact:
        page_url = _required(options, "page_url")
        pattern = _required(options, "asset_pattern")
        page = self.client.get(page_url).decode("utf-8", errors="replace")
        matches = re.findall(
            rf'href=["\']([^"\']*{re.escape(pattern)}[^"\']*\.apk)["\']',
            page,
            flags=re.IGNORECASE,
        )
        if not matches:
            raise ProviderError(f"no APK matching {pattern!r} at {page_url}")
        href = html.unescape(matches[0])
        url = urllib.parse.urljoin(page_url, href)
        return ResolvedArtifact(url, urllib.parse.unquote(url.rsplit("/", 1)[-1]))

    def _https(self, options: dict[str, Any]) -> ResolvedArtifact:
        url = _required(options, "url")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
        }:
            raise ProviderError("direct downloads must use HTTPS")
        filename = str(options.get("filename") or parsed.path.rsplit("/", 1)[-1])
        if not filename:
            raise ProviderError("HTTPS source requires a filename")
        return ResolvedArtifact(url, filename, sha256=_optional(options, "sha256"))

    def _pcloud(self, options: dict[str, Any]) -> ResolvedArtifact:
        folder_code = _required(options, "folder_code")
        pattern = _required(options, "pattern")
        listing = self.client.json(
            "https://api.pcloud.com/showpublink?"
            + urllib.parse.urlencode({"code": folder_code})
        )
        if not isinstance(listing, dict) or listing.get("result", 1) != 0:
            raise ProviderError("pCloud folder lookup failed")
        contents = listing.get("metadata", {}).get("contents", [])
        matches = [
            item
            for item in contents
            if isinstance(item, dict) and pattern in str(item.get("name", ""))
        ]
        if not matches:
            raise ProviderError(f"no pCloud file matching {pattern!r}")
        latest = max(matches, key=lambda item: str(item.get("name", "")))
        download = self.client.json(
            "https://api.pcloud.com/getpublinkdownload?"
            + urllib.parse.urlencode(
                {"code": folder_code, "fileid": int(latest["fileid"])}
            )
        )
        hosts = download.get("hosts", []) if isinstance(download, dict) else []
        path = download.get("path", "") if isinstance(download, dict) else ""
        if not hosts or not path:
            raise ProviderError("pCloud did not return a download URL")
        return ResolvedArtifact(f"https://{hosts[0]}{path}", str(latest["name"]))

    def _search_fdroid(self, query: str) -> list[SearchResult]:
        data = self.client.json("https://f-droid.org/api/v1/packages")
        packages = data if isinstance(data, list) else data.get("packages", [])
        lowered = query.casefold()
        results: list[SearchResult] = []
        for item in packages:
            if not isinstance(item, dict):
                continue
            package_id = str(item.get("packageName") or item.get("packageName", ""))
            name = str(item.get("name") or package_id)
            summary = str(item.get("summary") or "")
            if lowered not in f"{name} {package_id} {summary}".casefold():
                continue
            results.append(
                SearchResult(
                    "fdroid",
                    name,
                    package_id,
                    f"https://f-droid.org/packages/{package_id}/",
                    summary,
                )
            )
        return results[:25]

    def _search_apkmirror(self, query: str) -> list[SearchResult]:
        url = "https://www.apkmirror.com/?" + urllib.parse.urlencode(
            {"post_type": "app_release", "searchtype": "apk", "s": query}
        )
        page = self.client.get(url).decode("utf-8", errors="replace")
        matches = re.findall(
            r'<a[^>]+href=["\'](/apk/[^"\']+)["\'][^>]*>(.*?)</a>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        results: list[SearchResult] = []
        seen: set[str] = set()
        for path, raw_name in matches:
            name = re.sub(r"<[^>]+>", "", raw_name).strip()
            absolute = urllib.parse.urljoin("https://www.apkmirror.com", path)
            if not name or absolute in seen:
                continue
            seen.add(absolute)
            results.append(
                SearchResult("apkmirror", html.unescape(name), path, absolute)
            )
            if len(results) == 25:
                break
        return results

    @staticmethod
    def _resolve_secrets(
        options: dict[str, Any], secrets: dict[str, str]
    ) -> dict[str, Any]:
        resolved = dict(options)
        secret_ref = resolved.pop("secret_ref", None)
        secret_field = resolved.pop("secret_field", None)
        if secret_ref or secret_field:
            if not isinstance(secret_ref, str) or not isinstance(secret_field, str):
                raise ConfigError("source secret_ref and secret_field must be strings")
            value = secrets.get(secret_ref)
            if not value:
                raise ConfigError(f"missing secret {secret_ref!r}")
            resolved[secret_field] = value
        return resolved


def _required(options: dict[str, Any], key: str) -> str:
    value = options.get(key)
    if not isinstance(value, str) or not value:
        raise ProviderError(f"provider option {key!r} is required")
    return value


def _optional(options: dict[str, Any], key: str) -> str | None:
    value = options.get(key)
    return value if isinstance(value, str) and value else None
