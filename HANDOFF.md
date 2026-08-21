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

### Nikon D40 — working

Capture is verified end to end on the Pi: `gphoto2 --auto-detect` sees
`Nikon DSC D40 (PTP mode)`, and `scripts/test_camera.py` pulls a 3008x2000
baseline JPEG.

**2.4s per frame, shutter fires at t+0-1s.** Verified against EXIF with the
camera clock synced to the Pi. The trigger-to-shutter latency is under a
second, so no slicer gcode wait is needed.

Getting there was entirely about exposure settings. At `shutterspeed 2.5s`
/ `ISO 3200` a frame cost **8.1s** with the shutter firing 5-6s late — the
delay scales with exposure time, it is not fixed camera overhead. Adding light
alone changes nothing in M mode, because M ignores metering: the shutter stays
open exactly as long as you told it to. The fix is a fast shutter, not Auto.

Working settings, all writable over PTP:

```bash
gphoto2 --set-config shutterspeed=1/125
gphoto2 --set-config iso=400
```

```
expprogram M    shutterspeed 1/125   f/4.5    iso 400
imagequality JPEG Fine   imagesize 3008x2000  focusmode Manual
whitebalance Daylight    longexpnr Off
capturemode Burst   <- should be Single; the D40 rejects this PTP write
```

Stay in **M**, not Auto. Auto is fast for the same reason (it picks a quick
shutter in good light) but re-meters every frame, so brightness and colour
drift across the timelapse, and on the Auto dial position the D40 pops its
built-in flash — firing on every layer, draining the battery.

Do not add light and leave the shutter slow; that just overexposes. Frames are
~2.1 MB well-exposed (a 185 KB frame means under- or overexposed and flat).
At ~2 MB, a 300-frame print is ~600 MB against 110 GB free.

Things that do **not** affect speed, all measured: persistent session via
`gphoto2 --shell` (saves 0.5s), `capturetarget` card vs internal RAM, and
`longexpnr`.

The camera clock was ~7s off and has been synced to the Pi, so EXIF timestamps
are trustworthy.

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
