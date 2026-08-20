from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from android_setup.errors import ConfigError

PROFILE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,48}$")
APP_ID = re.compile(r"^[a-z][a-z0-9-]{0,48}$")
SUPPORTED_PROVIDERS = {"github", "fdroid", "html", "https", "pcloud"}
SUPPORTED_FILE_TYPES = {"binary", "json", "sqlite", "text", "zip"}


def _mapping(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{context} must be an object")
    return value


def _string(value: object, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigError(f"{context} must be a non-empty string")
    return value


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{context} must be a list of strings")
    return list(value)


@dataclass(frozen=True)
class SourceSpec:
    provider: str
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: object, context: str) -> SourceSpec:
        data = _mapping(value, context)
        provider = _string(data.get("provider"), f"{context}.provider")
        if provider not in SUPPORTED_PROVIDERS:
            raise ConfigError(
                f"{context}.provider must be one of {sorted(SUPPORTED_PROVIDERS)}"
            )
        return cls(
            provider, {key: item for key, item in data.items() if key != "provider"}
        )

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, **self.options}


@dataclass(frozen=True)
class AppSpec:
    id: str
    name: str
    package_id: str
    source: SourceSpec
    certificate_sha256: str | None = None
    architecture: str = "arm64-v8a"

    @classmethod
    def from_dict(cls, value: object, context: str = "app") -> AppSpec:
        data = _mapping(value, context)
        app_id = _string(data.get("id"), f"{context}.id")
        if not APP_ID.fullmatch(app_id):
            raise ConfigError(f"{context}.id has an invalid slug")
        certificate = data.get("certificate_sha256")
        if certificate is not None:
            certificate = _string(certificate, f"{context}.certificate_sha256")
            certificate = certificate.replace(":", "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", certificate):
                raise ConfigError(f"{context}.certificate_sha256 must be SHA-256 hex")
        return cls(
            id=app_id,
            name=_string(data.get("name"), f"{context}.name"),
            package_id=_string(data.get("package_id"), f"{context}.package_id"),
            source=SourceSpec.from_dict(data.get("source"), f"{context}.source"),
            certificate_sha256=certificate,
            architecture=_string(
                data.get("architecture", "arm64-v8a"), f"{context}.architecture"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "package_id": self.package_id,
            "architecture": self.architecture,
            "source": self.source.to_dict(),
        }
        if self.certificate_sha256:
            result["certificate_sha256"] = self.certificate_sha256
        return result


@dataclass(frozen=True)
class FileSpec:
    id: str
    name: str
    source: SourceSpec
    destination: str
    file_type: str = "binary"
    sha256: str | None = None
    extract_member: str | None = None
    extract_type: str | None = None

    @classmethod
    def from_dict(cls, value: object, context: str = "file") -> FileSpec:
        data = _mapping(value, context)
        file_id = _string(data.get("id"), f"{context}.id")
        if not APP_ID.fullmatch(file_id):
            raise ConfigError(f"{context}.id has an invalid slug")
        destination = _string(data.get("destination"), f"{context}.destination")
        path = PurePosixPath(destination)
        if not path.is_absolute() or ".." in path.parts:
            raise ConfigError(f"{context}.destination must be a safe absolute path")
        file_type = _string(data.get("type", "binary"), f"{context}.type")
        if file_type not in SUPPORTED_FILE_TYPES:
            raise ConfigError(
                f"{context}.type must be one of {sorted(SUPPORTED_FILE_TYPES)}"
            )
        sha256 = data.get("sha256")
        if sha256 is not None:
            sha256 = _string(sha256, f"{context}.sha256").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ConfigError(f"{context}.sha256 must be SHA-256 hex")
        extract_member = data.get("extract_member")
        extract_type = data.get("extract_type")
        if extract_member is not None:
            extract_member = _string(extract_member, f"{context}.extract_member")
            if file_type != "zip":
                raise ConfigError(f"{context}.extract_member requires type 'zip'")
            extract_type = _string(extract_type or "binary", f"{context}.extract_type")
            if extract_type not in SUPPORTED_FILE_TYPES - {"zip"}:
                raise ConfigError(f"{context}.extract_type is not supported")
        elif extract_type is not None:
            raise ConfigError(f"{context}.extract_type requires extract_member")
        return cls(
            id=file_id,
            name=_string(data.get("name"), f"{context}.name"),
            source=SourceSpec.from_dict(data.get("source"), f"{context}.source"),
            destination=destination.rstrip("/") or "/",
            file_type=file_type,
            sha256=sha256,
            extract_member=extract_member,
            extract_type=extract_type,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "destination": self.destination,
            "type": self.file_type,
            "source": self.source.to_dict(),
        }
        if self.sha256:
            result["sha256"] = self.sha256
        if self.extract_member:
            result["extract_member"] = self.extract_member
            result["extract_type"] = self.extract_type
        return result


@dataclass(frozen=True)
class BaseProfile:
    schema_version: int
    required_apps: tuple[AppSpec, ...]

    @classmethod
    def from_dict(cls, value: object) -> BaseProfile:
        data = _mapping(value, "base profile")
        version = data.get("schema_version")
        if version != 1:
            raise ConfigError("base profile schema_version must be 1")
        apps = data.get("required_apps")
        if not isinstance(apps, list):
            raise ConfigError("base profile required_apps must be a list")
        parsed = tuple(
            AppSpec.from_dict(app, f"required_apps[{index}]")
            for index, app in enumerate(apps)
        )
        _ensure_unique((app.id for app in parsed), "required app ids")
        return cls(version, parsed)


@dataclass(frozen=True)
class Profile:
    schema_version: int
    name: str
    description: str
    apps: tuple[AppSpec, ...]
    directories: tuple[str, ...]
    files: tuple[FileSpec, ...]
    instructions: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object) -> Profile:
        data = _mapping(value, "profile")
        if data.get("schema_version") != 1:
            raise ConfigError("profile schema_version must be 1")
        name = _string(data.get("name"), "profile.name")
        if not PROFILE_NAME.fullmatch(name):
            raise ConfigError("profile.name must be a lowercase slug")
        raw_apps = data.get("apps", [])
        raw_files = data.get("files", [])
        if not isinstance(raw_apps, list) or not isinstance(raw_files, list):
            raise ConfigError("profile apps and files must be lists")
        apps = tuple(
            AppSpec.from_dict(item, f"apps[{index}]")
            for index, item in enumerate(raw_apps)
        )
        files = tuple(
            FileSpec.from_dict(item, f"files[{index}]")
            for index, item in enumerate(raw_files)
        )
        directories = tuple(_string_list(data.get("directories", []), "directories"))
        for directory in directories:
            path = PurePosixPath(directory)
            if not path.is_absolute() or ".." in path.parts:
                raise ConfigError(f"unsafe Android directory: {directory}")
        _ensure_unique((app.id for app in apps), "app ids")
        _ensure_unique((item.id for item in files), "file ids")
        return cls(
            schema_version=1,
            name=name,
            description=_string(
                data.get("description", ""), "profile.description", allow_empty=True
            ),
            apps=apps,
            directories=directories,
            files=files,
            instructions=tuple(
                _string_list(data.get("instructions", []), "instructions")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "apps": [app.to_dict() for app in self.apps],
            "directories": list(self.directories),
            "files": [item.to_dict() for item in self.files],
            "instructions": list(self.instructions),
        }

    def effective_apps(self, base: BaseProfile) -> tuple[AppSpec, ...]:
        combined = (*base.required_apps, *self.apps)
        _ensure_unique((app.id for app in combined), "effective app ids")
        return combined


def _ensure_unique(values: Any, context: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ConfigError(f"duplicate {context}: {value}")
        seen.add(value)
