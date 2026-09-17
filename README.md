# ZeroCell

> **Experimental.** This tool writes non-volatile parameters on specific Huawei /
> Zong Bolt+ devices. On unsupported hardware or firmware it may not work at all,
> and the write can in rare cases make the device unusable or void its warranty.
> Use at your own risk. It does **not** bypass carrier or "Datalock" firmware
> locks; it only attempts the documented battery bypass for the listed devices.

![Status](https://img.shields.io/badge/status-experimental-orange)

One-click battery bypass for Huawei / Zong Bolt+ routers: put the device into
the "battery-less" (direct DC) mode via the HiLink API, then write the
firmware parameter that stops the battery check over its serial port.

The whole point is zero configuration: plug the device in, click **Start
Battery Bypass**, and read the result on a clean dark-theme screen.

Changed your mind? If the device is already in battery-less (direct DC) mode,
click **Restore Battery** to write the parameter back to `00 00 00 00` and
return it to normal battery operation.

## What it does

1. Connects to the device's web interface (`http://192.168.8.1`) and switches
   the network mode to `1`.
2. Waits ~5 s for the USB port to re-enumerate.
3. Finds the Huawei serial port (vendor `0x12D1`, prefers the "PC UI"
   interface) and writes the battery bypass parameter over AT commands.

**Restore Battery** runs the same flow but writes the zero payload
(`AT^NVWREX=50364,0,4,00 00 00 00`) instead of the bypass value.

## Requirements

- Python 3.11+
- Linux user must be in the `dialout` group (else the OS blocks the serial
  port): `sudo usermod -aG dialout $USER`, then **log out and back in**.
- A **Data Sync** USB cable. Charge-only cables will not connect to the router.
- This computer must reach the device at `http://192.168.8.1` — join the
  device's Wi-Fi, or use the network interface the USB cable exposes.

## Before you start

1. Insert the SIM card.
2. Insert the battery.
3. Power the device on.
4. Connect this computer to the device's Wi-Fi.
5. Connect the device to this computer with the Data Sync cable.
6. Press **Start Battery Bypass**.

## Install & run from source

```bash
git clone https://github.com/asim-ali-peerzada/huawei-battery-bypass.git
cd huawei-battery-bypass
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python src/main.py                 # Windows: python src\main.py
```

Ready-made binaries are attached to GitHub Releases:

- `ZeroCell.exe` (Windows)
- `zerocell-linux` (Ubuntu/Linux)

### Troubleshooting

- **"Device not detected on network"** — you are almost certainly using a
  charge-only cable, or the router is not powered on.
- **"Device not found" / no `/dev/ttyUSB*` port** — the kernel's `option`
  driver has not claimed the device. Load it and register the USB id (find the
  id with `lsusb | grep 12d1`):
  ```bash
  sudo modprobe option
  echo "12d1 1442" | sudo tee /sys/bus/usb-serial/drivers/option1/new_id
  ```
  Then replug the device and retry. Note the AT port number (`ttyUSB1`,
  `ttyUSB2`, …) can differ between machines; ZeroCell picks the "PC UI"
  interface automatically.
- **"ModemManager" / permission errors on Linux** — add your user to `dialout`
  and log out/in, or stop the service (temporarily):
  `sudo systemctl stop ModemManager`.
- **"Device firmware is locked (Datalock)"** — a firmware-level carrier lock.
  ZeroCell can not and will not bypass locks; an extra unlock step is required
  and is out of scope for this project.
- The **AT write affects firmware**; on devices where it is not supported the
  command may return `ERROR`. That is reported, not hidden.

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Quality gates (all used in CI):

```bash
ruff check src tests
ruff format --check src tests
mypy src
```

## Building the binaries

```bash
pyinstaller --onefile --windowed --collect-all customtkinter --paths src src/main.py
# name the output ZeroCell.exe (Windows) / zerocell-linux (Linux)
```

GitHub Actions builds both binaries automatically on every release and on
manual dispatch (Workflow runs → "Run workflow").

## Verification after a bypass

1. Plug the device into a laptop, insert battery, turn it on.
2. Click **Start**. Watch the three stages complete.
3. Unplug the device from the laptop, remove the battery entirely.
4. Plug the device directly into a 5V/2A wall charger.
5. The device should power on and join Wi-Fi without a battery and without
   the blinking red battery light.

If your device does not power on battery-less, it is simply not supported by
this parameter; no damage is implied.

## Reverting a bypass

1. Start the device and connect it to a laptop over the Data Sync cable.
2. Click **Restore Battery** and confirm the disclaimer.
3. Reinsert the battery and power on normally to confirm it charges and runs
   off the battery again.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Report vulnerabilities privately to the repository's Security policy tab —
never in a public issue.

## Credits

- [asim-ali-peerzada](https://github.com/asim-ali-peerzada)

## License

ZeroCell is open source under the [MIT License](LICENSE).