"""Tests for serial port discovery and AT command execution.

Regression tests for EDGE_CASES.md items:
- #2  locked/permission/vanished ports all reported as "Device not found"
- #3  AT handshake ERROR and NV-write ERROR collapsed into "Datalock"
- #10 no sub-step feedback during the port scan
- #19 empty response reported as Datalock
- #20 first Huawei port picked blindly (phone modem receiving NV writes)
"""

from __future__ import annotations

from unittest import mock

import pytest
import serial

from core.serial_manager import SerialManager
from utils.exceptions import (
    AtCommandError,
    DatalockError,
    DeviceDisconnectedError,
    DeviceNotRespondingError,
    DeviceNotSupportedError,
    ModemManagerError,
    NoSerialPortError,
    SerialPermissionError,
)


def make_port(device: str, vid: int | None, desc: str = "") -> mock.Mock:
    port = mock.Mock()
    port.device = device
    port.vid = vid
    port.description = desc
    return port


class TestFindPort:
    def test_prefers_pc_ui_description(self) -> None:
        manager = SerialManager()
        ports = [
            make_port("/dev/ttyUSB0", 0x12D1, "Huawei Mobile Connect"),
            make_port("/dev/ttyUSB2", 0x12D1, "HUAWEI Mobile Connect - PC UI"),
        ]
        with mock.patch("core.serial_manager.list_ports.comports", return_value=ports):
            assert manager.find_port(attempts=1) == "/dev/ttyUSB2"

    def test_single_huawei_without_pc_ui_is_used(self) -> None:
        manager = SerialManager()
        ports = [
            make_port("COM3", 0x12D1, "Huawei Mobile Connect"),
            make_port("COM4", 0x0BB4, "Some Other Device"),
        ]
        with mock.patch("core.serial_manager.list_ports.comports", return_value=ports):
            assert manager.find_port(attempts=1) == "COM3"

    def test_ambiguous_huawei_ports_without_pc_ui_are_refused(self) -> None:
        """#20: two Huawei ports, neither advertising PC UI → refuse to write."""
        manager = SerialManager()
        ports = [
            make_port("COM3", 0x12D1, "Huawei Mobile Connect"),
            make_port("COM4", 0x12D1, "Huawei Mobile Connect"),
        ]
        with mock.patch("core.serial_manager.list_ports.comports", return_value=ports):
            with pytest.raises(NoSerialPortError) as exc_info:
                manager.find_port(attempts=1)
        # The refusal must tell the user why, not just "not found".
        assert "huawei" in str(exc_info.value).lower()

    def test_pc_ui_wins_over_multiple_huawei_ports(self) -> None:
        """#20: a phone modem + router PC UI port → PC UI port is picked."""
        manager = SerialManager()
        ports = [
            make_port("COM3", 0x12D1, "HUAWEI Mobile Connect - Modem"),
            make_port("COM7", 0x12D1, "HUAWEI Mobile Connect - PC UI"),
        ]
        with mock.patch("core.serial_manager.list_ports.comports", return_value=ports):
            assert manager.find_port(attempts=1) == "COM7"
        assert manager.last_description == "HUAWEI Mobile Connect - PC UI"

    def test_raises_when_no_huawei_port(self) -> None:
        manager = SerialManager()
        with mock.patch("core.serial_manager.list_ports.comports", return_value=[]):
            with pytest.raises(NoSerialPortError) as exc_info:
                manager.find_port(attempts=1)
        # "Not found" alone is useless here: on most Linux hosts the port is
        # missing because the option driver never claimed the device.
        message = str(exc_info.value).lower()
        assert "ttyusb" in message
        assert "modprobe option" in message
        assert "new_id" in message

    def test_polls_until_port_appears(self) -> None:
        manager = SerialManager()
        ports = [make_port("/dev/ttyUSB0", 0x12D1, "PC UI")]
        with (
            mock.patch(
                "core.serial_manager.list_ports.comports",
                side_effect=[[], [], ports],
            ),
            mock.patch("time.sleep") as sleep,
        ):
            assert manager.find_port(attempts=5, delay_seconds=0.1) == "/dev/ttyUSB0"
            assert sleep.call_count == 2

    def test_reports_each_scan_attempt(self) -> None:
        """#10: the UI gets per-attempt feedback instead of a silent 6s freeze."""
        manager = SerialManager()
        seen: list[tuple[int, int]] = []
        with mock.patch("core.serial_manager.list_ports.comports", return_value=[]):
            with pytest.raises(NoSerialPortError):
                manager.find_port(
                    attempts=3, delay_seconds=0, on_attempt=lambda i, n: seen.append((i, n))
                )
        assert seen == [(1, 3), (2, 3), (3, 3)]

    def test_remembers_detected_port_and_description(self) -> None:
        """#15: controller/UI can show "Detected: ... on COM7"."""
        manager = SerialManager()
        ports = [make_port("COM7", 0x12D1, "HUAWEI Mobile Connect - PC UI")]
        with mock.patch("core.serial_manager.list_ports.comports", return_value=ports):
            manager.find_port(attempts=1)
        assert manager.last_port == "COM7"
        assert manager.last_description == "HUAWEI Mobile Connect - PC UI"


def open_patch(response: bytes) -> tuple[mock.Mock, object]:
    fake = mock.Mock()
    fake.read_until.return_value = response
    return fake, mock.patch("core.serial_manager._open", return_value=fake)


class TestOpenPortTranslation:
    """#2: pyserial's generic SerialException → real cause, real fix."""

    def _raises(self, message: str, expected: type[Exception]) -> None:
        manager = SerialManager()
        exc = serial.SerialException(message)
        with mock.patch("core.serial_manager._open", side_effect=exc):
            with pytest.raises(expected):
                manager.write_battery_bypass("/dev/ttyUSB0")

    def test_permission_denied_names_dialout_fix(self) -> None:
        self._raises("could not open port: Permission denied", SerialPermissionError)

    def test_busy_port_names_modemmanager(self) -> None:
        """#9/#2: ModemManagerError is actually raised now, not dead code."""
        self._raises("Port is busy or resource is locked", ModemManagerError)

    def test_port_gone_means_replug_message(self) -> None:
        self._raises(
            "could not open port /dev/ttyUSB0: No such file or directory", DeviceDisconnectedError
        )

    def test_unparseable_error_still_raises_something_specific(self) -> None:
        self._raises("weird unknown failure", DeviceDisconnectedError)


class TestWriteBypass:
    def test_sends_ping_then_nvwrite_and_returns_on_ok(self) -> None:
        manager = SerialManager()
        fake = mock.Mock()
        fake.read_until.return_value = b"OK\r\n"
        with mock.patch("serial.Serial", return_value=fake) as serial_cls:
            manager.write_battery_bypass("/dev/ttyUSB0")
        serial_cls.assert_called_once_with("/dev/ttyUSB0", baudrate=115200, timeout=3)
        writes = [call.args[0] for call in fake.write.call_args_list]
        assert writes[0] == b"AT\r\n"
        assert writes[1] == b"AT^NVWREX=50364,0,4,01 00 00 00\r\n"
        fake.close.assert_called_once()

    def test_explicit_datalock_tokens_raise_datalock(self) -> None:
        """#3: Datalock is reserved for an explicit lock signal from the device."""
        manager = SerialManager()
        for token in (b"DATALOCK\r\n", b"+CME ERROR: 3\r\n"):
            fake, patcher = open_patch(token)
            with patcher:
                with pytest.raises(DatalockError):
                    manager.write_battery_bypass("/dev/ttyUSB0")

    def test_at_handshake_error_is_not_datalock(self) -> None:
        """#3: ERROR to bare AT = port isn't an AT interface, not a firmware lock."""
        manager = SerialManager()
        fake, patcher = open_patch(b"ERROR\r\n")
        with patcher:
            with pytest.raises(AtCommandError):
                manager.write_battery_bypass("/dev/ttyUSB0")

    def test_nv_write_error_is_not_supported_not_datalock(self) -> None:
        """#3: README says plain ERROR on NV write means "unsupported, no damage"."""
        manager = SerialManager()
        fake = mock.Mock()
        fake.read_until.side_effect = [b"OK\r\n", b"ERROR\r\n"]
        with mock.patch("core.serial_manager._open", return_value=fake):
            with pytest.raises(DeviceNotSupportedError):
                manager.write_battery_bypass("/dev/ttyUSB0")

    def test_empty_response_means_not_responding_not_datalock(self) -> None:
        """#19: device returns nothing → "stopped responding", not "Datalock"."""
        manager = SerialManager()
        fake, patcher = open_patch(b"")
        with patcher:
            with pytest.raises(DeviceNotRespondingError):
                manager.write_battery_bypass("/dev/ttyUSB0")

    def test_garbage_response_mid_nv_write_means_not_responding(self) -> None:
        manager = SerialManager()
        fake = mock.Mock()
        fake.read_until.side_effect = [b"OK\r\n", b"junk\xff\x00"]
        with mock.patch("core.serial_manager._open", return_value=fake):
            with pytest.raises(DeviceNotRespondingError):
                manager.write_battery_bypass("/dev/ttyUSB0")

    def test_port_closed_even_on_datalock(self) -> None:
        manager = SerialManager()
        fake, patcher = open_patch(b"DATALOCK\r\n")
        with patcher:
            with pytest.raises(DatalockError):
                manager.write_battery_bypass("/dev/ttyUSB0")
        fake.close.assert_called_once()

    def test_port_closed_even_on_unexpected_error(self) -> None:
        manager = SerialManager()
        fake, patcher = open_patch(b"OK\r\n")
        fake.write.side_effect = OSError("yanked")
        with patcher:
            with pytest.raises(OSError):
                manager.write_battery_bypass("/dev/ttyUSB0")
        fake.close.assert_called_once()


class TestWriteRestore:
    """Revert path: NV 50364 must be zeroed to bring the battery back."""

    def test_sends_zero_payload_after_handshake(self) -> None:
        manager = SerialManager()
        fake = mock.Mock()
        fake.read_until.return_value = b"OK\r\n"
        with mock.patch("serial.Serial", return_value=fake):
            manager.write_battery_restore("/dev/ttyUSB0")
        writes = [call.args[0] for call in fake.write.call_args_list]
        assert writes[0] == b"AT\r\n"
        assert writes[1] == b"AT^NVWREX=50364,0,4,00 00 00 00\r\n"
        fake.close.assert_called_once()

    def test_open_error_still_translated(self) -> None:
        manager = SerialManager()
        exc = serial.SerialException("Port is busy or resource is locked")
        with mock.patch("core.serial_manager._open", side_effect=exc):
            with pytest.raises(ModemManagerError):
                manager.write_battery_restore("/dev/ttyUSB0")
