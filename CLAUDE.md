# BambuCam

Autonomous DSLR timelapse system for Bambu Lab A1 3D printer.

## What This Is

A Python daemon that runs on a Raspberry Pi 3B, listens for layer-change
trigger pulses from a Bambu Lab CyberBrick Timelapse Trigger, captures a
DSLR photo via gphoto2, and after the print completes: compiles frames into
an MP4 with ffmpeg, uploads to Appwrite (or other backends), verifies, and
cleans up.

## Architecture

- **State machine** drives the pipeline: IDLE → PRINT_STARTING → CAPTURING →
  COMPILING → UPLOADING → VERIFYING → CLEANUP → IDLE
- **Pluggable interfaces** for: trigger source, camera, printer events, upload
  backend, video compiler
- **Crash recovery** on startup by scanning prints/ directory and resuming
  unfinished jobs
- See SPEC.md for full specification

## Project Structure

```
bambucam/           # Python package
  daemon.py         # Entry point
  orchestrator.py   # Pipeline coordinator
  state_machine.py  # State enum + transitions
  models.py         # Dataclasses
  config.py         # YAML + env var config loader
  camera/           # CameraService implementations
  trigger/          # TriggerProvider implementations
  printer/          # PrinterProvider implementations
  compiler/         # Video compiler implementations
  upload/           # Uploader implementations
config/             # Configuration files
scripts/            # Test utilities
systemd/            # Service files
tests/              # Test suite
```

## Tech Stack

- Python 3.12
- gphoto2 (CLI via subprocess) for Nikon D40 capture
- RPi.GPIO for trigger detection
- ffmpeg for video compilation
- Appwrite SDK for upload
- PyYAML for configuration
- systemd for daemon management

## Commands

```bash
# Run daemon
python -m bambucam.daemon

# Run tests
pytest

# Test camera
python scripts/test_camera.py

# Test GPIO trigger
python scripts/test_gpio.py

# Test upload
python scripts/test_upload.py
```

## Configuration

Copy `config/config.yaml.example` to `config/config.yaml`.
Secrets go in `.env` file (never committed).

## Design Priorities

1. Reliability — must run unattended for months
2. Recoverability — must survive power loss at any point
3. Simplicity — no clever tricks
4. Image quality
5. Performance
