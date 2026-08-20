from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from android_setup.errors import ConfigError
from android_setup.models import PROFILE_NAME, BaseProfile, Profile


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.profiles_dir = self.root / "profiles"
        self.base_path = self.profiles_dir / "base.json"
        self.secrets_dir = self.profiles_dir / ".secrets"

    def load_base(self) -> BaseProfile:
        return BaseProfile.from_dict(self._read_json(self.base_path))

    def list(self) -> list[Profile]:
        if not self.profiles_dir.is_dir():
            raise ConfigError(f"profiles directory not found: {self.profiles_dir}")
        paths = (
            path
            for path in sorted(self.profiles_dir.glob("*.json"))
            if path.name != "base.json" and not path.name.startswith(".")
        )
        return [self.load(path.stem) for path in paths]

    def load(self, name: str) -> Profile:
        self._validate_name(name)
        path = self.profiles_dir / f"{name}.json"
        if not path.is_file():
            raise ConfigError(f"profile not found: {name}")
        profile = Profile.from_dict(self._read_json(path))
        if profile.name != name:
            raise ConfigError(
                f"profile filename and name differ: {name} != {profile.name}"
            )
        profile.effective_apps(self.load_base())
        return profile

    def add(self, name: str, from_name: str | None = None) -> Profile:
        self._validate_name(name)
        path = self.profiles_dir / f"{name}.json"
        if path.exists():
            raise ConfigError(f"profile already exists: {name}")
        if from_name:
            profile = replace(self.load(from_name), name=name)
        else:
            profile = Profile(1, name, "", (), (), (), ())
        self._write_json_atomic(path, profile.to_dict())
        return profile

    def save(self, profile: Profile) -> None:
        self._validate_name(profile.name)
        profile.effective_apps(self.load_base())
        self._write_json_atomic(
            self.profiles_dir / f"{profile.name}.json", profile.to_dict()
        )

    def edit(self, name: str, editor: str | None = None) -> Profile:
        current = self.load(name)
        selected = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not selected:
            raise ConfigError("set $VISUAL or $EDITOR before using profiles edit")
        with tempfile.TemporaryDirectory(prefix="android-setup-edit-") as temp_dir:
            temp_path = Path(temp_dir) / f"{name}.json"
            shutil.copy2(self.profiles_dir / f"{name}.json", temp_path)
            result = subprocess.run(
                [*shlex.split(selected), str(temp_path)], check=False
            )
            if result.returncode != 0:
                raise ConfigError(f"editor exited with status {result.returncode}")
            updated = Profile.from_dict(self._read_json(temp_path))
            if updated.name != current.name:
                raise ConfigError("profiles edit cannot rename a profile")
            self.save(updated)
            return updated

    def remove(self, name: str) -> None:
        self.load(name)
        (self.profiles_dir / f"{name}.json").unlink()

    def secrets(self, name: str) -> dict[str, str]:
        self._validate_name(name)
        path = self.secrets_dir / f"{name}.json"
        if not path.exists():
            return {}
        data = self._read_json(path)
        if not isinstance(data, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in data.items()
        ):
            raise ConfigError(f"secret file must contain string values: {path}")
        return data

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError as exc:
            raise ConfigError(f"configuration file not found: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"could not read JSON {path}: {exc}") from exc

    @staticmethod
    def _write_json_atomic(path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_name(name: str) -> None:
        if not PROFILE_NAME.fullmatch(name):
            raise ConfigError("profile name must be a lowercase slug")
