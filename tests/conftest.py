"""Shared pytest fixtures for the ZeroCell test suite.

The fakes mirror the *real* method signatures (including the on_attempt /
on_detail / cancel kwargs the controller passes) so a signature drift fails
here instead of silently skipping a step.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

from utils.exceptions import BypassError


class FakeApiClient:
    """In-memory stand-in for HiLinkApiClient."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.mode_calls = 0
        self.closed = False

    def fetch_token(self) -> str:
        if self.fail:
            raise ConnectionError("device not reachable")
        return "tok123"

    def switch_to_mode_1(self) -> None:
        self.mode_calls += 1

    def close(self) -> None:
        self.closed = True


class FakeSerialManager:
    """In-memory stand-in for SerialManager, matching the real signature."""

    def __init__(
        self,
        *,
        no_port: bool = False,
        datalock: bool = False,
        not_supported: bool = False,
    ) -> None:
        self.no_port = no_port
        self.datalock = datalock
        self.not_supported = not_supported
        self.written = False
        self.last_port = ""
        self.last_description = ""

    def find_port(
        self,
        attempts: int = 10,
        delay_seconds: float = 0.0,
        on_attempt: Callable[[int, int], None] | None = None,
    ) -> str:
        if on_attempt is not None:
            on_attempt(1, attempts)
        if self.no_port:
            from utils.exceptions import NoSerialPortError

            raise NoSerialPortError()
        # Mirror the real manager: report the attempt that found the port.
        if on_attempt is not None:
            on_attempt(1, attempts)
        self.last_port = "/dev/ttyUSB0"
        self.last_description = "HUAWEI Mobile Connect - PC UI"
        return self.last_port

    def write_battery_bypass(self, port: str) -> None:
        if self.datalock:
            from utils.exceptions import DatalockError

            raise DatalockError(port)
        if self.not_supported:
            from utils.exceptions import DeviceNotSupportedError

            raise DeviceNotSupportedError()
        self.written = True


class FakeController:
    """Stands in for BypassController in UI tests; records cancel usage."""

    def __init__(self, *, fail: str | None = None, cancel_check: bool = False) -> None:
        self.fail = fail
        self.cancel_check = cancel_check
        self.ran = 0
        self.cancel: threading.Event | None = None

    def run(
        self,
        on_step: Callable[[Any], None] | None = None,
        on_detail: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> bool:
        self.ran += 1
        self.cancel = cancel
        if on_step:
            on_step("CONNECTING")
            on_step("SWITCHING")
        if self.fail:
            raise BypassError(self.fail)
        if on_step:
            on_step("APPLYING")
        return True


@pytest.fixture
def fake_api() -> FakeApiClient:
    return FakeApiClient()


@pytest.fixture
def fake_serial() -> FakeSerialManager:
    return FakeSerialManager()
