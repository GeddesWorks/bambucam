# BambuCam Local Session Handoff

## What This Is

You are continuing setup of BambuCam — an autonomous DSLR timelapse system
for a Bambu Lab A1 3D printer. The codebase is complete and all 40 tests pass.
You need to deploy it to hardware and configure the integrations.

## What's Done

- Full Python project on branch `claude/new-project-spec-023uvp`
- State machine, orchestrator, pluggable interfaces (camera, trigger, printer, compiler, uploader)
- Bambuddy webhook integration (auto-detects Bambuddy payloads)
- Mock camera + NoOp uploader for testing without hardware
- Pi setup script, systemd service, sample config
- 40 passing tests
- Read SPEC.md for the full architecture

## What Needs To Happen

### 1. Set Up the Raspberry Pi

SSH into the Pi and deploy BambuCam.
(Credentials: ask the user or check their session notes.)

```bash
# SSH in, then:
sudo apt-get update && sudo apt-get install -y git

# Clone and run setup
sudo git clone -b claude/new-project-spec-023uvp \
  https://github.com/GeddesWorks/bambucam.git /opt/bambucam
cd /opt/bambucam
sudo bash scripts/setup_pi.sh
```

The setup script installs gphoto2, ffmpeg, Python venv, systemd service.
After it runs:

- Edit `/opt/bambucam/.env` with Appwrite credentials (or leave blank for now)
- For initial testing, set upload backend to `none` in config:
  edit `/opt/bambucam/config/config.yaml`, set `upload: backend: none`
- Set `camera: type: mock` in config until the Nikon D40 is connected
- Start the service: `sudo systemctl start bambucam`
- Check logs: `journalctl -u bambucam -f`
- Test health: `curl http://localhost:8420/health`

### 2. Configure Bambuddy Webhook

Bambuddy is running on Proxmox LXC 139. Access its web UI (likely
`http://<proxmox-ip>:8000` or whatever port LXC 139 exposes).

API key: already generated — ask the user for it or check their session notes.

In Bambuddy's web UI:
1. Settings → Notifications → Add Notification Provider
2. Type: Webhook
3. Name: BambuCam Timelapse
4. URL: `http://192.168.1.209:8420/`
5. Payload Format: Generic
6. Enable events: Print Start, Print Complete, Print Failed, Print Stopped
7. Save

The printer to record is called "Jeff" at IP 192.168.1.241.

To test the webhook manually:
```bash
curl -X POST http://192.168.1.209:8420/ \
  -H "Content-Type: application/json" \
  -d '{"source":"Bambuddy","event":"print_start","printer":"Jeff","filename":"test.gcode","timestamp":"2026-01-01T00:00:00"}'
```

### 3. Verify End-to-End (with mocks)

With camera=mock and upload=none, send a fake print cycle:
```bash
# Start print
curl -X POST http://192.168.1.209:8420/ \
  -H "Content-Type: application/json" \
  -d '{"source":"Bambuddy","event":"print_start","printer":"Jeff","filename":"test-benchy.gcode","timestamp":"2026-08-21T00:00:00"}'

# Simulate trigger pulses (if no GPIO, use the mock trigger test or
# modify config to use a manual/mock trigger)
# For now, check that the state changed to CAPTURING in the logs

# Complete print
curl -X POST http://192.168.1.209:8420/ \
  -H "Content-Type: application/json" \
  -d '{"source":"Bambuddy","event":"print_complete","printer":"Jeff","filename":"test-benchy.gcode","timestamp":"2026-08-21T01:00:00"}'
```

Check `/opt/bambucam/prints/` for the job directory and meta.json.

### 4. GPIO Trigger Wiring (when ready)

The CyberBrick timelapse trigger's 2.5mm jack is likely a contact closure
(shorts to ground on trigger). Wire it to GPIO pin 17:

- 2.5mm tip → GPIO 17
- 2.5mm sleeve → GND

Config is set to `edge: falling` with internal pull-up. The pin reads
HIGH normally, drops to LOW when triggered.

Test with: `/opt/bambucam/venv/bin/python /opt/bambucam/scripts/test_gpio.py 17 falling`

MEASURE THE SIGNAL WITH A MULTIMETER FIRST before connecting to the Pi.
If the trigger outputs voltage (not just a contact closure), you need
an optocoupler.

### 5. Real Camera

Once the Nikon D40 is connected via USB:
- Change config: `camera: type: gphoto2_cli`
- Test: `/opt/bambucam/venv/bin/python /opt/bambucam/scripts/test_camera.py`
- Restart service: `sudo systemctl restart bambucam`

The D40 must NOT be auto-mounted by gvfs — the setup script disables this,
but verify `gphoto2 --auto-detect` shows the camera.

### 6. Appwrite Upload (when ready)

Fill in `/opt/bambucam/.env`:
```
APPWRITE_ENDPOINT=https://your-appwrite-instance/v1
APPWRITE_PROJECT_ID=your-project-id
APPWRITE_API_KEY=your-api-key
APPWRITE_BUCKET_ID=your-bucket-id
```

Change config: `upload: backend: appwrite`
Test: `/opt/bambucam/venv/bin/python /opt/bambucam/scripts/test_upload.py`

## Key Details

- Branch: `claude/new-project-spec-023uvp`
- Repo: `GeddesWorks/bambucam`
- Pi IP: 192.168.1.209, user: collin
- Printer "Jeff": 192.168.1.241
- Bambuddy: LXC 139 (API key in user's session notes)
- BambuCam listens on port 8420
- Bambuddy runs on port 8000 by default

## User Preferences

- Owner: Collin Geddes (collin.geddes@gmail.com)
- Does not care about key rotation or Claude having keys
- Wants maximum autonomy — do as much as possible without asking
- Future: offload video compilation to Proxmox server instead of Pi
- Future: EP-5 dummy battery for camera continuous power (on order)

## Architecture Note

Video compilation on the Pi 3B will be slow (~5-10 min for 200 frames).
Collin wants to eventually offload this to Proxmox. When ready, build a
`RemoteFfmpegCompiler` that sends frames to a Proxmox container via
SSH/rsync for compilation and retrieves the output.mp4.
