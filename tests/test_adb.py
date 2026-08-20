from __future__ import annotations

from pathlib import Path

import pytest

from android_setup.adb import AdbClient, Device
from android_setup.errors import AdbError


class DeviceClient(AdbClient):
    def __init__(self, devices: list[Device]) -> None:
        super().__init__()
        self.available = devices

    def devices(self) -> list[Device]:
        return self.available


def test_device_selection_rules() -> None:
    one = Device("one", "device", "Phone One")
    two = Device("two", "device", "Phone Two")
    assert DeviceClient([one]).select_device(None, non_interactive=True) == one
    assert DeviceClient([one, two]).select_device("two", non_interactive=True) == two
    with pytest.raises(AdbError, match="multiple devices"):
        DeviceClient([one, two]).select_device(None, non_interactive=True)
    selected = DeviceClient([one, two]).select_device(
        None, non_interactive=False, input_fn=lambda _prompt: "1"
    )
    assert selected == one


def test_device_selection_rejects_missing_and_invalid() -> None:
    client = DeviceClient([])
    with pytest.raises(AdbError, match="no authorized"):
        client.select_device(None, non_interactive=False)
    one = Device("one", "device", "Phone")
    with pytest.raises(AdbError, match="not available"):
        DeviceClient([one]).select_device("missing", non_interactive=True)
    with pytest.raises(AdbError, match="invalid device selection"):
        DeviceClient([one, Device("two", "device", "Two")]).select_device(
            None, non_interactive=False, input_fn=lambda _prompt: "bad"
        )


def test_dry_run_prints_mutating_commands(tmp_path: Path) -> None:
    output: list[str] = []
    client = AdbClient("adb", dry_run=True, output=output.append)
    assert client._run(["install", "app.apk"], serial="serial") == ""
    assert output == ["DRY RUN: adb -s serial install app.apk"]
