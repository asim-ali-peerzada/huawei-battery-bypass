"""ZeroCell custom exceptions.

Each exception carries a message written for a non-technical user, and each
maps to exactly one real-world cause so the UI never tells the user to fix the
wrong thing. See EDGE_CASES.md.
"""

from __future__ import annotations

URL = "192.168.8.1"


class BypassError(Exception):
    """Base error with a user-friendly message."""


class BypassCancelled(BypassError):
    """The user closed the window / cancelled mid-run. Not a failure."""

    def __init__(self, msg: str = "Operation cancelled.") -> None:
        super().__init__(msg)


# --------------------------------------------------------------- network layer


class DeviceNotOnNetworkError(BypassError):
    """Nothing answered at the device's address (connection refused).

    Most common cause is a charge-only USB cable, so the message names the
    cable — but only when the failure really was "nothing there".
    """

    def __init__(
        self,
        msg: str = (
            f"No device found at {URL}. Connect the device with a Data Sync USB "
            "cable (not a charge-only cable), power it on, and try again."
        ),
    ) -> None:
        super().__init__(msg)


class DeviceUnreachableError(BypassError):
    """The address exists but did not answer in time (wrong IP / interface down)."""

    def __init__(
        self,
        msg: str = (
            f"The device did not respond at {URL} within the time limit. Check that "
            "it is powered on and its web interface is enabled, then retry."
        ),
    ) -> None:
        super().__init__(msg)


class DeviceRejectedError(BypassError):
    """The device answered but refused the request (HTTP error or XML code)."""

    def __init__(self, detail: str = "") -> None:
        msg = "The device refused the request."
        if detail:
            msg += f" It reported: {detail}."
        msg += " Reboot the device and retry; if it persists the firmware may be locked."
        super().__init__(msg)
        self.detail = detail


# Legacy name for the same failure; keep the old spelling working.
CableNotDataError = DeviceNotOnNetworkError


# ---------------------------------------------------------------- serial layer


class NoSerialPortError(BypassError):
    def __init__(
        self,
        msg: str = (
            "Device not found. Ensure it is plugged in and powered on. If no "
            "/dev/ttyUSB* port appears, the serial driver has not claimed it — run "
            "'sudo modprobe option', then register the device: "
            "'echo \"12d1 1442\" | sudo tee "
            "/sys/bus/usb-serial/drivers/option1/new_id' "
            "(the 4-digit id comes from 'lsusb | grep 12d1')."
        ),
    ) -> None:
        super().__init__(msg)


class DeviceDisconnectedError(BypassError):
    """The port vanished between discovery and use (USB re-enumeration race)."""

    def __init__(
        self,
        msg: str = (
            "The device disconnected during the process. Replug it, wait for it to "
            "power on, and try again."
        ),
    ) -> None:
        super().__init__(msg)


class SerialPermissionError(BypassError):
    """The OS refused access to the serial port (user not in dialout, etc.)."""

    def __init__(
        self,
        msg: str = (
            "Permission denied opening the serial port. On Linux run "
            "'sudo usermod -aG dialout $USER', then log out and back in."
        ),
    ) -> None:
        super().__init__(msg)


class ModemManagerError(BypassError):
    def __init__(
        self,
        msg: str = (
            "ModemManager is holding the serial port open. Run "
            "'sudo systemctl stop ModemManager' and try again."
        ),
    ) -> None:
        super().__init__(msg)


class AtCommandError(BypassError):
    """The port opened but did not answer AT — wrong interface or busy, not a lock."""

    def __init__(
        self,
        msg: str = (
            "The serial port did not answer AT commands. The device may be busy or "
            "the wrong interface was selected. Replug the device and retry."
        ),
    ) -> None:
        super().__init__(msg)


class DeviceNotRespondingError(BypassError):
    """The device stopped sending anything mid-command (cable yanked, port dead)."""

    def __init__(
        self,
        msg: str = "The device stopped responding. Replug it and try again.",
    ) -> None:
        super().__init__(msg)


class DeviceNotSupportedError(BypassError):
    """Plain AT ERROR from the NV write: this model likely doesn't support it."""

    def __init__(
        self,
        msg: str = (
            "The device rejected the bypass command. This model or firmware may not "
            "support it — no damage was done. See the README's supported-devices note."
        ),
    ) -> None:
        super().__init__(msg)


class DatalockError(BypassError):
    """Reserved for an explicit datalock signal from the device."""

    def __init__(
        self,
        port: str = "",
        msg: str = "Device firmware is locked (Datalock). Additional unlock may be required.",
    ) -> None:
        super().__init__(msg)
        self.port = port
