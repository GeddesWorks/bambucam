# BambuCam Deployment Handoff

Branch: `claude/new-project-spec-023uvp` · Repo: `GeddesWorks/bambucam` (public)

## Status

| Step | State |
|---|---|
| Codebase + tests | Done — 50 tests pass on the Pi |
| Deployed to the Pi | Done — `bambulapse` at **192.168.1.243**, running and enabled at boot |
| End-to-end pipeline verified with mocks | Done — on the Pi itself |
| Bambuddy webhook configured + delivering | Done — provider id 1, scoped to Jeff |
| CyberBrick trigger wired | Done — pin 17, verified firing the camera |
| Full chain dry run | Done — 8 presses, 8 frames, compiled to MP4 |
| Nikon D40 capture | Done — 2.4s per frame, zero failures |
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

### GPIO trigger — wired and working

CyberBrick shutter port → GPIO 17 (physical pin 11), sleeve → GND (pin 9).
Measured with `scripts/probe_gpio.py`: idle HIGH, **~100ms LOW pulse**, zero
bounce (the controller switches solid-state, not a relay). A dry contact
closure with no voltage on the line, so it drives the pin directly with no
optocoupler or series resistor.

The mono (2-contact) plug in use shorts the jack's ring to sleeve, holding
"focus" asserted permanently. Harmless with no camera on that port — but do not
plug this same cable into a camera.

**`debounce_ms` must be BELOW the pulse width, not above it.** This is inverted
from legacy RPi.GPIO and cost a full debugging cycle. Current Raspberry Pi OS
supplies rpi-lgpio, where `bouncetime` becomes
`lgpio.gpio_set_debounce_micros`: the level must stay stable for the whole
debounce period before the edge is reported, rather than suppressing further
edges after reporting one. The old 200ms default exceeded the 100ms pulse, so
every trigger was silently discarded — the daemon sat in CAPTURING and captured
nothing, with no error anywhere in the log. Default is now 20ms.

Symptom to recognise: `probe_gpio.py` (which polls) sees every pulse while the
daemon sees none. That combination means the debounce filter, not the wiring.

Verified on hardware: 8 button presses produced 8 frames, no retries, no
failures, compiled to a 3008x2000 MP4.

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

### Camera exposure — measured on a live print

Working settings, verified sharp and correctly exposed on the A1:

```
shutterspeed 1/125   f/3.5 (wide open)   iso 1600   expprogram M
```

**Shoot no slower than 1/125.** The A1 is a bed-slinger, and the bed is still
moving (or settling) when the shutter fires even with timelapse mode enabled.
Measured: 1/125 sharp, 1/60 sharp, **1/30 visibly smeared** — the plate and part
blur horizontally while the toolhead and rail stay sharp, which is the tell that
it is bed motion and not camera shake. Checking that the toolhead is parked
proves nothing; check the bed.

The fix that buys back image quality is a dwell at layer change, in Bambu
Studio under Printer Settings -> Machine G-code -> Layer change G-code:

```gcode
G4 P2000
```

Two seconds costs ~8 min over 243 layers and guarantees a stationary bed,
which allows 1/60 at ISO 400 instead of ISO 1600 — a large noise improvement on
a D40. Untested as of this writing: whether the CyberBrick fires as the park
begins or after it completes. If frames are still soft, lengthen the dwell.

**Measure the subject, not the frame.** `signalstats` YAVG over the whole
image is dominated by the bright wall and reads ~30 points high. Crop to the
plate first:

```bash
ffprobe -v error -f lavfi "movie=FRAME.jpg,crop=2000:640:450:800,signalstats"   -show_entries frame_tags=lavfi.signalstats.YAVG -of csv=p=0
```

Target ~110-120 on the plate region. For reference: 58 is clearly too dark, 24
is unusable.

**A brightness number cannot detect blur.** A frame measured 106 and looked
like a success while being badly smeared. Always pull the actual image and look
at it before declaring an exposure change good. File size is not an exposure
signal either — a dark noisy frame can be large.

All exposure settings are writable over PTP with `gphoto2 --set-config`, so
they can be corrected mid-print without touching the camera. `capturemode` is
the exception; the D40 rejects that write.

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
