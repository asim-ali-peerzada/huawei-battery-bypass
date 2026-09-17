"""Serial port discovery and AT command execution for Huawei devices."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import serial
from serial.tools import list_ports

from utils.exceptions import (
    AtCommandError,
    BypassError,
    DatalockError,
    DeviceDisconnectedError,
    DeviceNotRespondingError,
    DeviceNotSupportedError,
    ModemManagerError,
    NoSerialPortError,
    SerialPermissionError,
)

logger = logging.getLogger("zerocell.serial")

_HUAWEI_VID = 0x12D1
_PC_UI = "PC UI"
_BAUD = 115200
_TIMEOUT = 3
_NV_ENABLE = b"AT^NVWREX=50364,0,4,01 00 00 00\r\n"
_NV_RESTORE = b"AT^NVWREX=50364,0,4,00 00 00 00\r\n"
# The device signals an actual firmware lock explicitly; plain ERROR does not.
_DATALOCK_TOKENS = (b"DATALOCK", b"DATALOCKED", b"+CME ERROR: 3")


def _open(port: str) -> serial.Serial:
    """Open the raw port. pyserial's generic errors are translated by the caller."""
    return serial.Serial(port, baudrate=_BAUD, timeout=_TIMEOUT)


def _translate_open_error(exc: serial.SerialException) -> BypassError:
    """Turn pyserial's one generic SerialException into the real cause + fix."""
    text = str(exc).lower()
    if "permission" in text or "denied" in text:
        return SerialPermissionError()
    if "busy" in text or "resource" in text:
        return ModemManagerError()
    # Vanished, unplugged, unrecognised: all "reconnect the cable" territory.
    return DeviceDisconnectedError()


class SerialManager:
    def __init__(self) -> None:
        self.last_port = ""
        self.last_description = ""

    def find_port(
        self,
        attempts: int = 10,
        delay_seconds: float = 0.5,
        on_attempt: Callable[[int, int], None] | None = None,
    ) -> str:
        for attempt in range(1, attempts + 1):
            if on_attempt is not None:
                on_attempt(attempt, attempts)
            ports = list_ports.comports()
            huawei = [p for p in ports if getattr(p, "vid", None) == _HUAWEI_VID]
            pc_ui = [p for p in huawei if _PC_UI in (p.description or "")]
            if pc_ui:
                self._remember(pc_ui[0])
                logger.info("found PC UI port %s", pc_ui[0].device)
                return pc_ui[0].device
            if len(huawei) == 1:
                self._remember(huawei[0])
                logger.info("found huawei port %s", huawei[0].device)
                return huawei[0].device
            if len(huawei) > 1:
                # Several Huawei ports and none advertises PC UI: refusing is
                # safer than writing an NV command to (say) a phone's modem.
                raise NoSerialPortError(
                    "Multiple Huawei devices detected and none is the 'PC UI' port. "
                    "Unplug other Huawei devices and retry."
                )
            if attempt < attempts:
                logger.debug("no huawei port yet, attempt %d/%d", attempt, attempts)
                time.sleep(delay_seconds)
        raise NoSerialPortError()

    def _remember(self, port: object) -> None:
        self.last_port = str(getattr(port, "device", ""))
        self.last_description = str(getattr(port, "description", ""))

    def write_battery_bypass(self, port: str) -> None:
        """NV 50364 = 01… : run directly off DC (battery bypass on)."""
        self._write_nv(port, _NV_ENABLE)

    def write_battery_restore(self, port: str) -> None:
        """NV 50364 = 00… : revert to normal battery operation."""
        self._write_nv(port, _NV_RESTORE)

    def _write_nv(self, port: str, payload: bytes) -> None:
        try:
            conn = _open(port)
        except serial.SerialException as exc:
            raise _translate_open_error(exc) from exc
        try:
            self._handshake(conn)
            logger.info("AT OK, sending NV write")
            conn.write(payload)
            self._read_ok(conn, at_phase=False, port=port)
            logger.info("NV write OK")
        finally:
            conn.close()

    @staticmethod
    def _read_ok(conn: serial.Serial, *, at_phase: bool, port: str = "") -> bytes:
        resp = conn.read_until(b"OK", size=64)
        if not resp:
            raise DeviceNotRespondingError()
        upper = resp.upper()
        if any(token in upper for token in _DATALOCK_TOKENS):
            raise DatalockError(port)
        if b"OK" in upper:
            return resp
        if b"ERROR" in upper:
            # A plain ERROR to a bare AT probe means the port isn't an AT
            # interface; to the NV write it means the model doesn't support it.
            raise AtCommandError() if at_phase else DeviceNotSupportedError()
        if at_phase:
            raise AtCommandError()
        raise DeviceNotRespondingError()

    def _handshake(self, conn: serial.Serial) -> None:
        conn.write(b"AT\r\n")
        self._read_ok(conn, at_phase=True)
