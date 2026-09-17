"""Tests for the bypass orchestration flow.

Regression tests for EDGE_CASES.md items:
- #7/#23 cancellation between steps (window closed mid-run)
- #10 scan sub-step detail is forwarded to the UI
- #15 detected device info is captured for the status card
- #14 api.close() runs even when the run fails
"""

from __future__ import annotations

import threading
from unittest import mock

import pytest

from core.bypass_controller import BypassController, Step
from utils.exceptions import BypassCancelled, BypassError, NoSerialPortError


@pytest.fixture
def controller(fake_api, fake_serial) -> BypassController:
    return BypassController(fake_api, fake_serial, wait_seconds=0)


class TestSuccessfulFlow:
    def test_runs_all_steps_in_order(self, controller, fake_api, fake_serial) -> None:
        events: list[Step] = []
        result = controller.run(on_step=events.append)
        assert events == [Step.CONNECTING, Step.SWITCHING, Step.APPLYING]
        assert result is True
        assert fake_api.mode_calls == 1
        assert fake_serial.written is True

    def test_closes_api_in_finally(self, controller, fake_api) -> None:
        controller.run()
        assert fake_api.closed is True

    def test_closes_api_when_serial_step_raises(self, controller, fake_api, fake_serial) -> None:
        """#14: close() must run even when the serial step explodes."""
        with mock.patch.object(fake_serial, "write_battery_bypass", side_effect=OSError("yanked")):
            with pytest.raises(BypassError):
                controller.run()
        assert fake_api.closed is True


class TestFailureHalts:
    def test_api_failure_skips_serial_step(self, controller, fake_api, fake_serial) -> None:
        fake_api.fail = True
        events: list[Step] = []
        with pytest.raises(BypassError) as exc_info:
            controller.run(on_step=events.append)
        assert events == [Step.CONNECTING]
        assert fake_serial.written is False
        assert fake_api.closed is True
        assert "device not reachable" in str(exc_info.value).lower()

    def test_no_port_raises_with_user_message(self, controller, fake_serial) -> None:
        fake_serial.no_port = True
        with pytest.raises(NoSerialPortError):
            controller.run()

    def test_datalock_raises_firmware_message(self, controller, fake_serial) -> None:
        fake_serial.datalock = True
        with pytest.raises(BypassError) as exc_info:
            controller.run()
        assert "firmware" in str(exc_info.value).lower()

    def test_unsupported_device_raises_support_message(self, controller, fake_serial) -> None:
        """#3: unsupported ≠ locked; the message must not say "firmware locked"."""
        fake_serial.not_supported = True
        with pytest.raises(BypassError) as exc_info:
            controller.run()
        text = str(exc_info.value).lower()
        assert "locked" not in text
        assert "support" in text

    def test_unexpected_error_becomes_human_message(self, controller, fake_serial) -> None:
        with mock.patch.object(
            fake_serial, "write_battery_bypass", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(BypassError) as exc_info:
                controller.run()
        assert "boom" in str(exc_info.value)


class TestCancellation:
    """#7/#23: the controller must stop between steps when asked."""

    def test_cancel_event_stops_before_mode_switch(self, fake_api, fake_serial) -> None:
        controller = BypassController(fake_api, fake_serial, wait_seconds=0)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(BypassCancelled):
            controller.run(cancel=cancel)
        assert fake_api.mode_calls == 0
        assert fake_serial.written is False

    def test_cancel_event_stops_before_serial_write(self, fake_api, fake_serial) -> None:
        controller = BypassController(fake_api, fake_serial, wait_seconds=0)
        cancel = threading.Event()

        def set_after_mode() -> None:
            fake_api.mode_calls += 1
            cancel.set()

        with mock.patch.object(fake_api, "switch_to_mode_1", side_effect=set_after_mode):
            with pytest.raises(BypassCancelled):
                controller.run(cancel=cancel)
        assert fake_serial.written is False

    def test_cancel_event_stops_during_reenumeration_wait(self, fake_api, fake_serial) -> None:
        controller = BypassController(fake_api, fake_serial, wait_seconds=5.0)
        cancel = threading.Event()

        def stop_soon() -> None:
            cancel.set()

        with mock.patch.object(fake_api, "switch_to_mode_1", side_effect=stop_soon):
            with pytest.raises(BypassCancelled):
                controller.run(cancel=cancel)
        assert fake_serial.written is False

    def test_close_api_on_cancel(self, fake_api, fake_serial) -> None:
        controller = BypassController(fake_api, fake_serial, wait_seconds=0)
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(BypassCancelled):
            controller.run(cancel=cancel)
        assert fake_api.closed is True


class TestSubStepDetail:
    def test_scan_detail_reaches_ui(self, controller, fake_serial) -> None:
        """#10: scan progress arrives as detail lines, not silence."""
        details: list[str] = []
        controller.run(on_detail=details.append)
        assert any("serial port" in d.lower() for d in details)
        assert any("waiting" in d.lower() for d in details)

    def test_detected_device_info_is_captured(self, controller, fake_serial) -> None:
        """#15: port + description are surfaced for the status card."""
        details: list[str] = []
        controller.run(on_detail=details.append)
        assert controller.detected_port == "/dev/ttyUSB0"
        assert "PC UI" in controller.detected_description
        assert any("Detected:" in d for d in details)


class TestRestoreFlow:
    """Reversing an existing bypass must write the zero payload, not the one."""

    def test_restore_run_writes_revert_payload(self, controller, fake_serial) -> None:
        assert controller.run(restore=True) is True
        assert fake_serial.restored is True
        assert fake_serial.written is False

    def test_restore_run_still_walks_all_steps(self, controller) -> None:
        events: list[Step] = []
        controller.run(on_step=events.append, restore=True)
        assert events == [Step.CONNECTING, Step.SWITCHING, Step.APPLYING]

    def test_default_run_does_not_restore(self, controller, fake_serial) -> None:
        controller.run()
        assert fake_serial.written is True
        assert fake_serial.restored is False
