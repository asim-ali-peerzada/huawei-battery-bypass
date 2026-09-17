"""ZeroCell entry point."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from core.api_client import HiLinkApiClient
from core.bypass_controller import BypassController
from core.serial_manager import SerialManager
from utils.logger import setup_logger
from utils.version import __version__


def self_test() -> int:
    """Headless import check for packaged binaries."""
    import customtkinter

    from ui import app, components  # noqa: F401

    print(f"ZeroCell v{__version__} self-test OK (customtkinter {customtkinter.__version__})")
    return 0


def _acquire_instance_lock() -> object | None:
    """Stop two copies fighting over the same serial port.

    Returns a handle to keep alive, or False if another copy already holds the
    lock. Returns None on platforms without fcntl (the guard is a no-op there).
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        return None
    lock = open(Path(tempfile.gettempdir()) / "zerocell.lock", "w")  # noqa: SIM115
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return False
    return lock


def main() -> int:
    argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()

    lock = _acquire_instance_lock()
    if lock is False:
        from tkinter import messagebox

        messagebox.showwarning("ZeroCell", "ZeroCell is already running.")
        return 1

    setup_logger()
    controller = BypassController(HiLinkApiClient(), SerialManager())

    from ui.app import ZeroCellApp

    app = ZeroCellApp(controller)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
