# BambuCam Deployment Handoff

Branch: `claude/new-project-spec-023uvp` · Repo: `GeddesWorks/bambucam` (public)

## Status

| Step | State |
|---|---|
| Codebase + tests | Done — 50 tests pass (1 skips without ffprobe) |
| End-to-end pipeline verified with mocks | Done (on a Linux stand-in host, not the Pi) |
| Bambuddy webhook provider configured | Done — provider id 1, scoped to Jeff, pointed at the Pi |
| Deploy to the Pi | **Blocked — SSH credentials rejected** |
| GPIO trigger wiring | Not started (hardware) |
| Nikon D40 capture | Not started (hardware) |
| Appwrite upload | Not started (needs credentials) |

## Blocked: Pi SSH

`192.168.1.209` answers on port 22 (`OpenSSH_10.0p2 Debian-7`) and offers
`publickey,password`, but `collin` + the supplied password is rejected. Tried
`collin`, `pi`, `Collin`, and the local `~/.ssh/id_ed25519` key. Port 22 is the
only open port on the Pi. Correct credentials (or an authorized public key) are
needed before deployment can proceed.

## Deploying to the Pi

Once SSH works:

```bash
sudo apt-get update && sudo apt-get install -y git
sudo git clone -b claude/new-project-spec-023uvp \
  https://github.com/GeddesWorks/bambucam.git /opt/bambucam
sudo bash /opt/bambucam/scripts/setup_pi.sh
```

`setup_pi.sh` installs gphoto2, ffmpeg, the Python venv, a GPIO library
(`rpi-lgpio`, falling back to `RPi.GPIO`), and the systemd unit. It does not
start the service.

Then put `/opt/bambucam/config/config.yaml` into mock mode for the first run:

```yaml
trigger:
  type: mock            # fires a fake pulse every interval_seconds
  interval_seconds: 5
camera:
  type: mock            # writes a valid 64x64 placeholder JPEG per frame
upload:
  backend: none         # NoOpUploader — compiles the video, uploads nothing
```

```bash
sudo systemctl start bambucam
journalctl -u bambucam -f
curl http://localhost:8420/health
```

## Verifying end to end

This exact sequence was run against a Linux stand-in and passed all the way
through `IDLE → CAPTURING → COMPILING → UPLOADING → VERIFYING → CLEANUP`:

```bash
curl -X POST http://192.168.1.243:8420/ -H 'Content-Type: application/json' \
  -d '{"source":"Bambuddy","event":"print_start","printer":"Jeff","filename":"test-benchy.gcode"}'

# wait ~20s — mock trigger fires every 5s, frames land in prints/<job>/frames/

curl -X POST http://192.168.1.243:8420/ -H 'Content-Type: application/json' \
  -d '{"source":"Bambuddy","event":"print_complete","printer":"Jeff","filename":"test-benchy.gcode"}'
```

Expect `/opt/bambucam/prints/<job-id>/meta.json` with `video_compiled: true`,
`upload_status: verified`, and (with cleanup enabled) frames and video removed.

## Bambuddy — already configured

Bambuddy is LXC 139 on node `BIG`, reachable at `http://192.168.1.90:8000`.
Notification provider id 1 is created and enabled:

- Name: `BambuCam Timelapse`
- Type: webhook, payload format `generic`
- URL: `http://192.168.1.209:8420/`
- Scoped to `printer_id: 1` (Jeff, 192.168.1.241) — Esmirelda is printer 2 and
  will not trigger captures
- Events: print start / complete / failed / stopped only; everything else off

Delivery was verified for real: Bambuddy's own test send reached a running
BambuCam instance and was acknowledged. Bambuddy's generic payload carries
`event` plus the template variables (`printer`, `filename`, …) at the top
level, which is what `bambucam/printer/http.py` parses.

Re-test at any time:

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
  pin idles HIGH and drops LOW on trigger)
- Test: `/opt/bambucam/venv/bin/python /opt/bambucam/scripts/test_gpio.py 17 falling`

If the daemon logs `TRIGGER_UNAVAILABLE` at startup, the GPIO library did not
install — the daemon runs but captures nothing.

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
