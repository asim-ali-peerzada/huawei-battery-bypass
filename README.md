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

## What it does

1. Connects to the device's web interface (`http://192.168.8.1`) and switches
   the network mode to `1`.
2. Waits ~5 s for the USB port to re-enumerate.
3. Finds the Huawei serial port (vendor `0x12D1`, prefers the "PC UI"
   interface) and writes the battery bypass parameter over AT commands.

## Requirements

- Python 3.11+
- Linux user must be in the `dialout` group (else the OS blocks the serial
  port): `sudo usermod -aG dialout $USER`, then **log out and back in**.
- A **Data Sync** USB cable. Charge-only cables will not connect to the router.

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