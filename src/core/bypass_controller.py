"""Orchestrates the API + Serial bypass workflow."""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable

from core.api_client import HiLinkApiClient
from core.serial_manager import SerialManager
from utils.exceptions import BypassCancelled, BypassError

logger = logging.getLogger("zerocell.controller")

STEP_ORDER = ("CONNECTING", "SWITCHING", "APPLYING")


class Step(enum.Enum):
    CONNECTING = "Connecting to device..."
    SWITCHING = "Switching modes (device may blink)..."
    APPLYING = "Applying bypass..."

    def __str__(self) -> str:
        return self.value


class BypassController:
    def __init__(
        self,
        api: HiLinkApiClient,
        serial: SerialManager,
        wait_seconds: float = 4.5,
        poll_attempts: int = 12,
        poll_delay: float = 0.5,
    ) -> None:
        self.api = api
        self.serial = serial
        self.wait_seconds = wait_seconds
        self.poll_attempts = poll_attempts
        self.poll_delay = poll_delay
        self.detected_port = ""
        self.detected_description = ""

    def run(
        self,
        on_step: Callable[[Step], None] | None = None,
        on_detail: Callable[[str], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> bool:
        def notify(step: Step) -> None:
            if on_step:
                on_step(step)
            logger.info(str(step))

        def detail(text: str) -> None:
            if on_detail:
                on_detail(text)
            logger.debug("%s", text)

        def check() -> None:
            if cancel is not None and cancel.is_set():
                raise BypassCancelled()

        try:
            notify(Step.CONNECTING)
            try:
                self.api.fetch_token()
            except BypassError:
                raise
            except Exception as exc:
                raise BypassError(str(exc)) from exc
            check()

            notify(Step.SWITCHING)
            detail("switching modes - Wi-Fi to the device will drop during this step")
            try:
                self.api.switch_to_mode_1()
            except BypassError:
                raise
            except Exception as exc:
                raise BypassError(str(exc)) from exc
            check()

            self._wait(self.wait_seconds, cancel, detail)

            notify(Step.APPLYING)
            try:
                port = self.serial.find_port(
                    attempts=self.poll_attempts,
                    delay_seconds=self.poll_delay,
                    on_attempt=lambda i, n: detail(f"waiting for serial port... {i}/{n}"),
                )
                self.detected_port = getattr(self.serial, "last_port", "") or port
                self.detected_description = getattr(self.serial, "last_description", "")
                if self.detected_description:
                    detail(f"Detected: {self.detected_description} on {self.detected_port}")
                else:
                    detail(f"Detected: device on {self.detected_port}")
                check()
                self.serial.write_battery_bypass(port)
            except BypassError:
                raise
            except Exception as exc:
                raise BypassError(f"Unexpected error while contacting the device: {exc}") from exc
            return True

        finally:
            try:
                self.api.close()
            except Exception:
                pass

    @staticmethod
    def _wait(
        seconds: float, cancel: threading.Event | None, detail: Callable[[str], None]
    ) -> None:
        """Sleep in cancellable slices, keeping the user informed."""
        logger.info("waiting %.1fs for USB re-enumeration", seconds)
        detail("waiting for the device to re-appear...")
        remaining = seconds
        while remaining > 0:
            if cancel is not None and cancel.is_set():
                raise BypassCancelled()
            slice_ = min(0.1, remaining)
            time.sleep(slice_)
            remaining -= slice_
