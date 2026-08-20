from __future__ import annotations

import fnmatch
import json
import os
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from android_setup.errors import ConfigError, ProviderError, ValidationError
from android_setup.models import BaseProfile, FileSpec, Profile
from android_setup.providers import USER_AGENT, ProviderRegistry, ResolvedArtifact
from android_setup.validation import validate_app, validate_file


@dataclass(frozen=True)
class ArtifactRecord:
    kind: str
    id: str
    name: str
    path: str
    source_url: str
    sha256: str
    version: str | None
    downloaded_at: str

    @classmethod
    def from_dict(cls, value: object) -> ArtifactRecord:
        if not isinstance(value, dict):
            raise ConfigError("artifact manifest entry must be an object")
        try:
            return cls(
                kind=str(value["kind"]),
                id=str(value["id"]),
                name=str(value["name"]),
                path=str(value["path"]),
                source_url=str(value["source_url"]),
                sha256=str(value["sha256"]),
                version=str(value["version"]) if value.get("version") else None,
                downloaded_at=str(value["downloaded_at"]),
            )
        except KeyError as exc:
            raise ConfigError(f"artifact manifest missing {exc.args[0]}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "source_url": self.source_url,
            "sha256": self.sha256,
            "version": self.version,
            "downloaded_at": self.downloaded_at,
        }


class ArtifactManager:
    def __init__(
        self,
        root: Path,
        providers: ProviderRegistry | None = None,
        *,
        require_android_tools: bool = True,
        download_retries: int = 3,
    ) -> None:
        self.root = root.resolve()
        self.providers = providers or ProviderRegistry()
        self.require_android_tools = require_android_tools
        self.download_retries = download_retries

    def profile_dir(self, profile: Profile) -> Path:
        return self.root / "artifacts" / profile.name

    def download(
        self, profile: Profile, base: BaseProfile, secrets: dict[str, str]
    ) -> list[ArtifactRecord]:
        target = self.profile_dir(profile)
        records: list[ArtifactRecord] = []
        for app in profile.effective_apps(base):
            resolved = self.providers.resolve(app.source, secrets)
            destination = target / "apks" / _safe_filename(resolved.filename)
            temporary = self._download_to_temporary(resolved, destination.parent)
            try:
                digest = validate_app(
                    temporary,
                    app,
                    resolved.sha256,
                    require_android_tools=self.require_android_tools,
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary.replace(destination)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            records.append(
                self._record(
                    "app", app.id, app.name, target, destination, resolved, digest
                )
            )
        for item in profile.files:
            resolved = self.providers.resolve(item.source, secrets)
            download_path = target / "files" / _safe_filename(resolved.filename)
            temporary = self._download_to_temporary(resolved, download_path.parent)
            try:
                digest = validate_file(temporary, item, resolved.sha256)
                download_path.parent.mkdir(parents=True, exist_ok=True)
                temporary.replace(download_path)
                final_path = download_path
                if item.extract_member:
                    final_path = self._extract_member(download_path, item)
                    extracted_spec = replace(
                        item,
                        file_type=item.extract_type or "binary",
                        sha256=None,
                        extract_member=None,
                        extract_type=None,
                    )
                    digest = validate_file(final_path, extracted_spec)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            records.append(
                self._record(
                    "file", item.id, item.name, target, final_path, resolved, digest
                )
            )
        self._write_manifest(profile, records)
        return records

    def verify(self, profile: Profile, base: BaseProfile) -> list[ArtifactRecord]:
        records = self.read_manifest(profile)
        record_map = {(record.kind, record.id): record for record in records}
        target = self.profile_dir(profile)
        for app in profile.effective_apps(base):
            record = _required_record(record_map, "app", app.id)
            path = _safe_manifest_path(target, record.path)
            validate_app(
                path,
                app,
                record.sha256,
                require_android_tools=self.require_android_tools,
            )
        for item in profile.files:
            record = _required_record(record_map, "file", item.id)
            path = _safe_manifest_path(target, record.path)
            verify_spec = item
            if item.extract_member:
                verify_spec = replace(
                    item,
                    file_type=item.extract_type or "binary",
                    sha256=None,
                    extract_member=None,
                    extract_type=None,
                )
            validate_file(path, verify_spec, record.sha256)
        return records

    def read_manifest(self, profile: Profile) -> list[ArtifactRecord]:
        path = self.profile_dir(profile) / "manifest.json"
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"could not read artifact manifest for {profile.name}: {exc}"
            ) from exc
        if not isinstance(data, dict) or data.get("profile") != profile.name:
            raise ConfigError(f"artifact manifest does not belong to {profile.name}")
        entries = data.get("artifacts")
        if not isinstance(entries, list):
            raise ConfigError("artifact manifest entries must be a list")
        return [ArtifactRecord.from_dict(entry) for entry in entries]

    def _download_to_temporary(
        self, resolved: ResolvedArtifact, directory: Path
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".download-", suffix=".part", dir=directory
        )
        os.close(fd)
        temp_path = Path(temporary)
        request = urllib.request.Request(
            resolved.url, headers={"User-Agent": USER_AGENT}
        )
        last_error: Exception | None = None
        for _attempt in range(self.download_retries):
            try:
                with temp_path.open("wb") as output:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                return temp_path
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last_error = exc
        temp_path.unlink(missing_ok=True)
        raise ProviderError(
            f"download failed for {resolved.url}: {last_error}"
        ) from last_error

    def _extract_member(self, archive_path: Path, item: FileSpec) -> Path:
        assert item.extract_member is not None
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                name
                for name in archive.namelist()
                if fnmatch.fnmatch(PurePosixPath(name).name, item.extract_member)
                and not name.endswith("/")
            ]
            if len(matches) != 1:
                raise ValidationError(
                    f"expected one ZIP member matching {item.extract_member!r}, "
                    f"found {len(matches)}"
                )
            member = matches[0]
            destination = archive_path.parent / _safe_filename(
                PurePosixPath(member).name
            )
            fd, temporary = tempfile.mkstemp(
                prefix=".extract-", dir=archive_path.parent
            )
            temp_path = Path(temporary)
            try:
                with os.fdopen(fd, "wb") as output, archive.open(member) as source:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                temp_path.replace(destination)
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
        archive_path.unlink()
        return destination

    def _write_manifest(self, profile: Profile, records: list[ArtifactRecord]) -> None:
        target = self.profile_dir(profile)
        target.mkdir(parents=True, exist_ok=True)
        path = target / "manifest.json"
        fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=target)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "profile": profile.name,
                        "artifacts": [record.to_dict() for record in records],
                    },
                    handle,
                    indent=2,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _record(
        kind: str,
        item_id: str,
        name: str,
        root: Path,
        path: Path,
        resolved: ResolvedArtifact,
        digest: str,
    ) -> ArtifactRecord:
        return ArtifactRecord(
            kind,
            item_id,
            name,
            str(path.relative_to(root)),
            resolved.url,
            digest,
            resolved.version,
            datetime.now(UTC).isoformat(),
        )


def _safe_filename(name: str) -> str:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ProviderError(f"unsafe provider filename: {name!r}")
    return name


def _safe_manifest_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ConfigError(f"unsafe path in artifact manifest: {relative}")
    return path


def _required_record(
    records: dict[tuple[str, str], ArtifactRecord], kind: str, item_id: str
) -> ArtifactRecord:
    try:
        return records[(kind, item_id)]
    except KeyError as exc:
        raise ConfigError(f"artifact manifest is missing {kind} {item_id}") from exc
