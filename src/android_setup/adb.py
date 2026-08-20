from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from android_setup.artifacts import ArtifactManager, ArtifactRecord
from android_setup.errors import AdbError
from android_setup.models import BaseProfile, Profile


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    model: str


class AdbClient:
    def __init__(
        self,
        executable: str = "adb",
        *,
        dry_run: bool = False,
        output: Callable[[str], None] = print,
    ) -> None:
        self.executable = executable
        self.dry_run = dry_run
        self.output = output

    def devices(self) -> list[Device]:
        result = self._run(["devices", "-l"], serial=None, mutate=False)
        devices: list[Device] = []
        for line in result.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 2:
                continue
            serial, state = fields[:2]
            model = next(
                (
                    field.removeprefix("model:")
                    for field in fields[2:]
                    if field.startswith("model:")
                ),
                "unknown",
            )
            devices.append(Device(serial, state, model))
        return devices

    def select_device(
        self,
        requested: str | None,
        *,
        non_interactive: bool,
        input_fn: Callable[[str], str] = input,
    ) -> Device:
        available = [device for device in self.devices() if device.state == "device"]
        if requested:
            match = next(
                (device for device in available if device.serial == requested), None
            )
            if not match:
                raise AdbError(f"ADB device not available: {requested}")
            return match
        if not available:
            raise AdbError("no authorized ADB devices are connected")
        if len(available) == 1:
            return available[0]
        if non_interactive:
            raise AdbError("multiple devices connected; pass --device SERIAL")
        self.output("Connected devices:")
        for index, device in enumerate(available, 1):
            self.output(f"  {index}. {device.model} ({device.serial})")
        answer = input_fn("Select device number: ").strip()
        try:
            return available[int(answer) - 1]
        except (ValueError, IndexError) as exc:
            raise AdbError("invalid device selection") from exc

    def provision(
        self,
        profile: Profile,
        base: BaseProfile,
        artifacts: ArtifactManager,
        device: Device,
    ) -> None:
        records = artifacts.verify(profile, base)
        record_map = {(record.kind, record.id): record for record in records}
        root = artifacts.profile_dir(profile)
        failures: list[str] = []
        for directory in profile.directories:
            try:
                self._run(["shell", "mkdir", "-p", directory], serial=device.serial)
            except AdbError as exc:
                failures.append(str(exc))
        for app in profile.effective_apps(base):
            record = _record(record_map, "app", app.id)
            try:
                self._run(
                    ["install", "-r", str(root / record.path)], serial=device.serial
                )
            except AdbError as exc:
                failures.append(str(exc))
        for item in profile.files:
            record = _record(record_map, "file", item.id)
            remote = str(PurePosixPath(item.destination) / Path(record.path).name)
            try:
                self._run(
                    ["push", str(root / record.path), remote], serial=device.serial
                )
            except AdbError as exc:
                failures.append(str(exc))
        if failures:
            raise AdbError(
                f"{len(failures)} provisioning operation(s) failed:\n"
                + "\n".join(f"- {failure}" for failure in failures)
            )
        for line in profile.instructions:
            self.output(line)

    def _run(
        self,
        arguments: list[str],
        *,
        serial: str | None,
        mutate: bool = True,
    ) -> str:
        command = [self.executable]
        if serial:
            command.extend(["-s", serial])
        command.extend(arguments)
        if self.dry_run and mutate:
            self.output("DRY RUN: " + " ".join(command))
            return ""
        try:
            result = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
        except OSError as exc:
            raise AdbError(f"could not execute {self.executable}: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise AdbError(f"{' '.join(command)} failed: {detail}")
        return result.stdout


def _record(
    records: dict[tuple[str, str], ArtifactRecord], kind: str, item_id: str
) -> ArtifactRecord:
    try:
        return records[(kind, item_id)]
    except KeyError as exc:
        raise AdbError(f"verified manifest is missing {kind} {item_id}") from exc
