# ZeroCell — Edge Cases, Bugs & Unhandled Paths

Audit of the real-world failure paths across `api_client` → `bypass_controller` →
`serial_manager` → UI. Prioritized by user harm: **a message that lies is worse
than a vague one**, because the user takes the wrong action.

---

## P0 — Messages that lie to the user

### 1. Every HTTP failure is reported as "charge-only cable"
**Where:** `api_client.py` `_get()` / `_post()` → `raise CableNotDataError()`

The same exception is raised for *all* of these very different situations:
- Device not connected at all (nothing at 192.168.8.1) → connection refused
- Device connected but web interface disabled / wrong IP → timeout
- Router on Wi-Fi but **USB plugged with a charge-only cable** → device reachable
  over Wi-Fi, so HTTP *works* — this is the one case the message is true for
- Device in a weird post-flash state returning HTTP 500 → raise_for_status

**The lie:** user whose device simply isn't plugged in is told to buy a data
cable. User who got HTTP 500 is told it's a cable problem. Fix: distinguish
`ConnectionError` (not on network) from `Timeout` (wrong IP / interface down)
from `HTTPError` (device responded, rejected us) — three messages, three fixes.

### 2. "Device not found" when the port exists but is locked or dead
**Where:** `serial_manager.py` `find_port()` → `NoSerialPortError("Device not found...")`

`find_port` scans `list_ports.comports()` for VID 0x12D1. If the port exists but
`serial.Serial(port, ...)` fails in `write_battery_bypass`, the resulting
`SerialException` is caught by the controller as generic `"Unexpected error
while contacting the device"` — but the *common* cause is:
- **ModemManager** has the port open (Linux) → should be `ModemManagerError`
  (which exists but is *never raised anywhere*)
- Permission denied (not in `dialout` group) → should say "run
  `sudo usermod -aG dialout $USER`", not "device not found"
- Port disappeared between scan and open (USB re-enumeration race) → should say
  "device disconnected during the process, replug and retry"

### 3. AT "ERROR" response reported as "Datalock"
**Where:** `serial_manager.py` `write_battery_bypass()` → `DatalockError(port)`

Both the `AT` handshake check and the NV write check collapse every non-`OK`
response into `DatalockError("Device firmware is locked (Datalock)")`. But:
- `AT` handshake failing is *not* a datalock — it means the port isn't
  accepting AT commands at all (wrong interface grabbed, device busy, ModemManager)
- The README itself says on unsupported devices the NV command may return
  `ERROR` — "no damage is implied" — yet the UI tells those users their
  firmware is "locked", which sounds alarming and irreversible

### 4. `switch_to_mode_1` never checks the response body
**Where:** `api_client.py` `switch_to_mode_1()`

`_post` only checks HTTP status. Huawei returns HTTP 200 with an XML body like
`<response><code>100003</code></response>` (not logged in / not allowed) or
`<response>OK</response>`. A rejected mode switch "succeeds", then the tool
waits 4.5s, scans for a serial port, and likely fails with the misleading
"Device not found" — the actual failure (mode switch rejected) is invisible.

---

## P1 — Real-world flow bugs

### 5. Mode-1 switch can disconnect the user from the device and strand the run
**Where:** `bypass_controller.py` step 1→2

If the user is connected to the router over Wi-Fi (not USB), switching to
mode 1 drops the Wi-Fi interface — the client can no longer talk to 192.168.8.1.
That's fine for this tool (subsequent steps use serial), but the UI never
warns "you will lose Wi-Fi to the router during this process". If the user is
on a laptop relying on that router for other work, it's a surprise outage.

### 6. Success message assumes wall-charger usage without checking
**Where:** `app.py` `_finish(True)`

Success text tells users to unplug, remove battery, and use a wall charger.
Fine. But `run_callback` returning `True` only means the NV write got `OK` —
it does **not** verify the mode stuck. There's no verification step (re-read
the NV param or re-query mode) so "Success" is really "write accepted". The
UI wording is honest ("Bypass command accepted") but the big green **Success**
headline overpromises — should be "Command accepted — verify on your device".

### 7. No device re-connect recovery / retry
**Where:** whole flow

If the user unplugs mid-run (knocks the cable), every step fails permanently
and they must restart the whole app from scratch for another attempt. The
controller raises once; the UI shows error; re-click Start does re-run, OK —
but `self._events` is re-created only in `_start()`. If the user closes the
window while the worker thread is running (`_on_close` sets `_closed` and
destroys), the daemon thread keeps executing `write_battery_bypass` — writing
to a serial port **after the GUI is gone**, with no cancellation mechanism.

### 8. Window close during a run = orphaned serial write
**Where:** `app.py` `_on_close`

`self._closed = True; self.destroy()` — the worker thread is daemon so the
process *usually* exits, but on some platforms (Windows) the process lingers
until the thread finishes. Worse, the AT/NV write may be mid-flight when the
port handle is left dangling. There should be a "running — are you sure?"
confirm, or a cancellation flag the worker checks between steps.

### 9. `ModemManagerError` exists but is never raised
**Where:** `utils/exceptions.py`, `serial_manager.py`

Dead code — the README dedicates a troubleshooting bullet to ModemManager, but
the code never detects or raises it. Users on Linux hit it constantly and get
a generic "Unexpected error" instead.

### 10. No timeout / no feedback on the serial scan phase
**Where:** `serial_manager.py` `find_port(attempts=12, delay=0.5)`

That's a ~6-second silent scan after a 4.5s wait — ~10.5 seconds of "Applying
bypass..." at 90% progress with zero detail. Users assume it froze. Either
stream sub-step detail ("waiting for serial port... attempt 3/12") or animate
the progress bar during the scan.

### 11. HTTP token endpoint fallback hides the real error
**Where:** `api_client.py` `fetch_token()`

If `/api/webserver/SesTokInfo` 404s (older firmware), it silently falls back
to `/api/webserver/token`. If *that* fails with a connection error, the
exception from the fallback is raised — losing the fact that the *first*
endpoint actually responded (device is there! it's a firmware difference), so
the cable message is doubly wrong here.

### 12. Progress bar jumps 0 → 15% → 50% → 90% → 100% with no in-between
**Where:** `app.py` `_set_step` / `_finish`

Combined with #10, the bar sits frozen at 90% for ~6 seconds (the serial scan)
then snaps to 100%. Enterprises use indeterminate "pulse" during unknown
duration; at minimum the serial phase should report incremental progress.

### 13. Success state leaves the checkbox disabled-then-re-enabled but never reset
**Where:** `app.py` `_finish` / `_fail`

After a run, `_confirm` stays checked (good for retry), but the StepTracker is
left showing the last step as active with no "done" state — after Success the
tracker shows step 3 still "● active" forever, which reads as "still working".
It should flip step 3 to green ✓ on success (it currently never does because
`set_current` marks it active, not done).

### 14. Two error paths, one swallow
**Where:** `bypass_controller.py` `run()`

`finally: self.api.close()` — good. But if `run_callback` is injected (tests
do this) and it raises a *non*-BypassError, the UI shows "Unexpected error: ..."
which is fine — except the exception message may contain a stack fragment or
raw library string shown verbatim to a nontechnical user. Should be mapped to
friendly copy with the detail sent to the log only.

### 15. No version / device info anywhere in the UI
**Where:** `app.py`

Enterprise tools always surface "what am I talking to". ZeroCell detects the
device (VID, port description) but never shows it. Adding a "Detected: Huawei
PC UI on COM7" line would make the tool feel trustworthy and make bug reports
useful. Conversely, on failure, the log file path is never surfaced in the UI —
users are told "review the log" with no hint where it is
(`~/.local/state/zerocell/zerocell.log`).

---

## P2 — Polish / robustness

### 16. `_start()` double-click race
`_busy` guards re-entry, but the guard is set after the confirm check — a
double-click in the same tick before `_busy = True` runs the whole flow twice.
The button is disabled after the first click processes, but the two events can
queue before that. Add an early `if self._busy: return` at the very top
(it's there) *and* disable the button immediately in the same handler before
any other work.

### 17. `Step` not in `_STEP_COPY` falls through with `-1` index
`_set_step` uses `.index(step)` guarded by a membership check — OK, but a new
`Step` enum member added to the controller would silently show no tracker
progress. `dict.get` on `_STEP_COPY` already handles the copy, but the index
lookup should use the same dict order instead of a hardcoded list.

### 18. `wraplength=400` is hardcoded
On the 520px window with 24px padding, fine — but if the window is widened the
text stays at 400px and looks ragged. Should derive from widget width or use a
constant next to the layout constants.

### 19. `SerialManager.write_battery_bypass` has no read timeout guard for no-response
`read_until(b"OK", size=64)` with `timeout=3` returns whatever arrived. If the
device returns nothing at all (unpowered port, cable yanked mid-write), resp
is empty → raises `DatalockError` (the lying-message problem again, see #3) —
should be "device stopped responding".

### 20. `find_port` picks the *first* Huawei port, not necessarily PC UI
If two Huawei devices are attached (e.g. a phone + the router), a phone's
modem port (also VID 0x12D1) could be picked and receive an NV write. Should
verify the port description or at least prefer "PC UI" and refuse to write to
a port that doesn't advertise it.

### 21. No single-instance guard
Two ZeroCell instances can both scan and both write to the same port. A
lockfile (`/tmp/zerocell.lock`) or a tkinter `singleinstance` check would
prevent the confusing interleaved failures.

### 22. Log file grows per run with no user-facing retention notice
Minor: 512KB rotating, fine — but the UI never mentions logs exist. One line
in the footer or on error ("Full details: ~/.local/state/zerocell/zerocell.log")
closes the loop.

### 23. `time.sleep` in worker thread can't be cancelled
`bypass_controller` sleeps 4.5s + serial polls up to 6s with no cancellation
check. Ties into #7/#8: closing the window mid-run can't interrupt these.

### 24. No DPI / scaling test on Windows
`customtkinter` handles DPI, but the fixed `wraplength`, `geometry("520x680")`,
and font sizes are unscaled px. On 150% Windows scaling, text can clip.
`customtkinter` auto-scales fonts but wraplength values set before widget
creation are scaled correctly — verify on a real HiDPI Windows box.

---

## Quick wins (smallest diffs, biggest honesty gain)

| # | Fix | File |
|---|-----|------|
| 1 | Split `CableNotDataError` into NotConnected / WrongNetwork / DeviceRejected | `api_client.py` |
| 2 | Map `SerialException` kinds (PermissionError, busy, gone) to specific errors | `serial_manager.py` |
| 3 | Rename NV-write ERROR to "device not supported" not "Datalock"; reserve Datalock for `AT` handshake fail | `serial_manager.py` |
| 4 | Check `<response>` body of mode switch, raise on `code` | `api_client.py` |
| 5 | Empty serial response → "device stopped responding" not Datalock | `serial_manager.py` |
| 6 | Confirm-on-close while busy; cancellation event checked between steps | `app.py`, `bypass_controller.py` |
| 7 | Step 3 shows ✓ done on success | `app.py` |
| 8 | Surface log path in error detail | `app.py` |
| 9 | Show detected device (port + description) in status card | `app.py` |
| 10 | Prefer PC UI port strictly; skip non-PC-UI Huawei ports when ambiguous | `serial_manager.py` |

---

## Resolution status (this pass)

34 tests pass; `ruff`, `mypy` clean. Verified by unit tests, not against physical
hardware. Items marked resolved were changed in code; nothing here is "documented
as fixed" without a matching code change.

| # | Status | What changed |
|---|--------|--------------|
| 1 | Resolved | `_request()` now raises `DeviceNotOnNetworkError` (connection refused), `DeviceUnreachableError` (timeout) or `DeviceRejectedError` (HTTP status). `CableNotDataError` kept as an alias for the network-absent case. |
| 2 | Resolved | `_open()` maps `SerialException`: permission → `SerialPermissionError` (dialout hint), busy → `ModemManagerError`, missing/gone → `DeviceDisconnectedError`. |
| 3 | Resolved | AT-probe `ERROR` → `AtCommandError`; NV-write `ERROR` → `DeviceNotSupportedError`; `DatalockError` only on an explicit `DATALOCK` / `+CME ERROR: 3` token. |
| 4 | Resolved | `_check_mode_response()` parses `<code>`; non-zero → `DeviceRejectedError`; requires `OK` or `code 0`. |
| 5 | Resolved | Controller streams "switching modes - Wi-Fi to the device will drop during this step" before the switch. |
| 6 | Resolved | Headline is now "Command accepted" (was "Success!"), with verify-on-device copy that does not claim the mode stuck. |
| 7 | Resolved | Re-clicking Start re-runs the flow; a cancellation event now lets a close interrupt the worker. No silent auto-retry — retrying a firmware write unattended is worse than asking. |
| 8 | Resolved | `_on_close` asks for confirmation while busy, sets the cancel event, then destroys. The controller checks cancel between steps and inside `_wait`. |
| 9 | Resolved | `ModemManagerError` is now raised from `_open()` on a busy port. |
| 10 | Resolved | `find_port(on_attempt=...)` streams "waiting for serial port... i/n"; the bar also advances (#12). |
| 11 | Resolved | Only a 404 triggers the legacy-token fallback; connection/timeout errors propagate instead of being masked. Test added. |
| 12 | Resolved | While busy, `_poll` nudges the bar toward a 0.92 ceiling; only real success sets 1.0. |
| 13 | Resolved by removal | The old StepTracker was deleted in the theme rewrite; the field "ledger" is static decorative labels. Active/done state is the numbered status ("2/3 ...") plus the progress bar, so no stale "active" marker remains. |
| 14 | Resolved | Unexpected exceptions are logged via `logger.exception` and shown as friendly copy + log path; the raw exception string no longer reaches the UI. |
| 15 | Resolved | Window title is `ZeroCell v0.1.0`; error copy includes the log path; the controller streams "Detected: <description> on <port>". |
| 16 | Resolved | `_busy` is set before the disclaimer check (and reset on the early return), so the same tick cannot start twice. |
| 17 | Resolved | `_set_step` uses `list(Step).index(step)`; adding an enum member updates the count automatically. |
| 18 | Resolved | `WRAP_FULL` / `WRAP_CARD` / `WRAP_NARROW` derive from `CONTENT_WIDTH`; no hardcoded wraplengths remain. |
| 19 | Resolved | An empty read → `DeviceNotRespondingError` in both the handshake and NV phases. |
| 20 | Resolved | `find_port` prefers "PC UI", accepts a single Huawei port, and refuses when several Huawei ports exist with none advertising PC UI. |
| 21 | Resolved | `main.py` takes an `fcntl.flock` on `/tmp/zerocell.lock`; no-op where `fcntl` is unavailable (Windows). |
| 22 | Resolved | The log path is surfaced on error via `utils.logger.log_path()`. |
| 23 | Resolved | `_wait` sleeps in 0.1 s slices checking the cancel event; each scan attempt is individually cancellable. |
| 24 | **Not verified** | No Windows HiDPI machine available. Mitigations already applied: fixed 460 px content column and wrap widths derived from it. Still needs a manual pass on a 150 %-scaled Windows box. |

### Residual / deliberate non-fixes

- **Wi-Fi-only users still lose connectivity** — warned, not prevented. The tool
  needs serial and assumes USB is connected.
- **No post-write verification** — success still means "NV write accepted". Reading
  the parameter back requires a device-specific read path that has not been
  captured; the UI wording is honest about this.
- **Physical hardware still untested** — every serial/AT path is covered only by
  mocks (`pyserial` `Serial` patched). Treat first hardware run as the real test.

