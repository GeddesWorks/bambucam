# BambuCam Deployment Handoff

Branch: `claude/new-project-spec-023uvp` · Repo: `GeddesWorks/bambucam` (public)

## Status

| Step | State |
|---|---|
| Codebase + tests | Done — 50 tests pass on the Pi |
| Deployed to the Pi | Done — `bambulapse` at **192.168.1.243**, running and enabled at boot |
| End-to-end pipeline verified with mocks | Done — on the Pi itself |
| Bambuddy webhook configured + delivering | Done — provider id 1, scoped to Jeff |
| GPIO edge detection | Verified working on pin 17 (nothing wired yet) |
| CyberBrick trigger wiring | Not started (hardware) |
| Nikon D40 capture | Not started (hardware) |
| Appwrite upload | Not started (needs credentials) |

## The Pi

**The Pi 3B is `192.168.1.243`, not `.209`.** `.209` is a different, newer Pi on
the network (`E4:5F:01` OUI); the 3B is `b8:27:eb:18:1d:3f`. Chasing `.209` is
what made the credentials look wrong at first.

- Hostname `bambulapse`, Debian 13 (trixie), kernel 6.18 aarch64, 4 cores, 905 MB RAM
- Currently on **ethernet**. Wi-Fi never associated — if you want it wireless
  that still needs sorting (`rfkill list`, then `nmcli device wifi connect`)
- The address is DHCP. Worth a reservation on the gateway, since the Bambuddy
  webhook URL is hardcoded to it
- `collin`'s SSH key auth is installed; sudo requires a password

## Current runtime state

`/opt/bambucam/config/config.yaml` is in full mock mode:

```yaml
trigger:  {type: mock, interval_seconds: 5}   # fake pulse every 5s
camera:   {type: mock}                        # valid 64x64 placeholder JPEG
upload:   {backend: none}                     # compiles video, uploads nothing
```

```bash
systemctl status bambucam
journalctl -u bambucam -f
curl http://192.168.1.243:8420/health
```

## Rebuilding from scratch

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone -b claude/new-project-spec-023uvp \
  https://github.com/GeddesWorks/bambucam.git /opt/bambucam
sudo bash /opt/bambucam/scripts/setup_pi.sh
```

Installs gphoto2, ffmpeg, the venv (with `--system-site-packages`), a working
GPIO library, and the systemd unit. It does not start the service.

## Verifying end to end

This exact sequence was run against the Pi and passed through
`IDLE → CAPTURING → COMPILING → UPLOADING → VERIFYING → CLEANUP`:

```bash
curl -X POST http://192.168.1.243:8420/ -H 'Content-Type: application/json' \
  -d '{"source":"Bambuddy","event":"print_start","printer":"Jeff","filename":"test-benchy.gcode"}'

# wait ~35s — mock trigger fires every 5s, frames land in prints/<job>/frames/

curl -X POST http://192.168.1.243:8420/ -H 'Content-Type: application/json' \
  -d '{"source":"Bambuddy","event":"print_complete","printer":"Jeff","filename":"test-benchy.gcode"}'
```

Result: 10 frames captured, `meta.json` with `video_compiled: true` and
`upload_status: verified`, frames and video cleaned up.

## Bambuddy — configured

Bambuddy is LXC 139 on node `BIG`, at `http://192.168.1.90:8000`. Notification
provider **id 1** is created and enabled:

- Name: `BambuCam Timelapse`, type webhook, payload format `generic`
- URL: `http://192.168.1.243:8420/`
- Scoped to `printer_id: 1` (Jeff, 192.168.1.241) — Esmirelda is printer 2 and
  will not trigger captures
- Events: print start / complete / failed / stopped only; everything else off

Delivery to the Pi is verified. Bambuddy's generic payload carries `event` plus
the template variables (`printer`, `filename`, …) at the top level, which is
what `bambucam/printer/http.py` parses.

```bash
curl -X POST -H "X-API-Key: $BAMBUDDY_API_KEY" \
  http://192.168.1.90:8000/api/v1/notifications/1/test
```

Not yet exercised: a genuine print event from Jeff. Bambuddy's
`/api/v1/printers/1/debug/simulate-print-complete` would do it, but it mutates
the most recent print archive record, so it was left alone — run a short real
print instead.

## Remaining hardware work

### GPIO trigger

MEASURE THE SIGNAL WITH A MULTIMETER FIRST. If the CyberBrick trigger outputs
voltage rather than a contact closure, an optocoupler is required.

- 2.5mm tip → GPIO 17, sleeve → GND
- Config: `trigger: {type: gpio, gpio_pin: 17, edge: falling}` (internal pull-up,
  pin idles HIGH and drops LOW on trigger — confirmed reading HIGH on the bench)
- Test: `/opt/bambucam/venv/bin/python /opt/bambucam/scripts/test_gpio.py 17 falling`

Edge detection is verified working. Note that legacy `RPi.GPIO` is broken on
this image — it imports and reads pins but `add_event_detect()` fails, so the
daemon looks healthy while the trigger never fires. The venv uses Debian's
`python3-rpi-lgpio` via `--system-site-packages`; do not `pip install RPi.GPIO`
into the venv, it shadows the working one.

### Nikon D40

- `camera: type: gphoto2_cli`
- Test: `/opt/bambucam/venv/bin/python /opt/bambucam/scripts/test_camera.py`
- Verify `gphoto2 --auto-detect` sees it; setup disables the gvfs auto-mount
  that otherwise grabs the camera

### Appwrite

Fill `/opt/bambucam/.env` (`APPWRITE_ENDPOINT`, `APPWRITE_PROJECT_ID`,
`APPWRITE_API_KEY`, `APPWRITE_BUCKET_ID`), set `upload: backend: appwrite`,
then `/opt/bambucam/venv/bin/python /opt/bambucam/scripts/test_upload.py`.

## Notes

- Video compilation on the Pi 3B will be slow (~5-10 min for 200 frames).
  Offloading to Proxmox via a `RemoteFfmpegCompiler` (rsync frames out, pull
  output.mp4 back) is the planned follow-up.
- `HttpPrinterProvider` does not filter on printer name; scoping is done in
  Bambuddy. If a second webhook source is ever added, add filtering here.
- EP-5 dummy battery for continuous camera power is on order.
