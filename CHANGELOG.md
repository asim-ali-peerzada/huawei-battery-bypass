# Changelog

All notable changes are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Single Terminal-style interface (dark, monospace, one accent) — the only
  look; no theme selection.
- HiLink API handshake (session token + Mode 1 switch) with charge-only-cable
  error detection.
- Huawei serial port auto-discovery (vendor `0x12D1`, PC UI preferred).
- `AT^NVWREX=50364,0,4,01 00 00 00` battery-bypass write with Datalock error
  reporting.
- ZeroCell `customtkinter` desktop app: Idle → Working → Success/Error states,
  worker-thread execution so the UI never freezes.
- File logging (rotating, never logs tokens or serial payloads).
- `pytest` suite covering API, serial, controller, and UI flows.
- CI (GitHub Actions): tests + lint + typecheck on Windows/Linux, PyInstaller
  builds for binaries on release.
- Single-instance guard (`fcntl` lock on `/tmp/zerocell.lock`).
- Cancellable run: closing the window mid-run asks for confirmation and signals
  the worker to stop at its next checkpoint.
- Live progress detail ("waiting for serial port... 3/12", "Detected: Huawei
  PC UI on /dev/ttyUSB0") streamed from the worker to the status line.

### Changed

- Failure messages now map to the real cause instead of blaming the cable for
  everything: connection-refused, timeout, HTTP rejection, permission denied,
  ModemManager, disconnected port, AT-interface mismatch, unsupported model and
  an explicit Datalock are each reported distinctly (see `EDGE_CASES.md`).
- The Mode 1 response body is validated; a non-zero `<code>` now fails at the
  switching step instead of surfacing later as a misleading serial error.
- Success headline reads "Command accepted — verify on your device" rather than
  claiming verified success; the progress bar no longer sits frozen during the
  serial scan and only fills fully on real success.
- Window title includes the version; error copy includes the log path.

### Fixed

- Legacy-token fallback no longer masks the original network error.
- Empty serial responses and a plain NV `ERROR` are no longer misreported as a
  firmware Datalock.
- `find_port` refuses to guess when multiple Huawei ports are present and none
  advertises PC UI.