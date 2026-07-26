# BambuCam — Project Specification

**Autonomous Bambu Lab A1 DSLR Timelapse System**

Version 0.1 — 2026-07-26

---

## 1. Mission

Build a fully autonomous timelapse appliance that captures one high-quality DSLR
still per layer during a Bambu Lab A1 print, compiles the frames into an MP4 at
print completion, uploads the video, verifies the upload, and cleans up local
files — with zero user interaction after initial setup.

```
Print starts → detect → create project → capture every layer →
detect completion → compile video → upload → verify → cleanup → idle
```

---

## 2. Hardware

| Component | Detail |
|---|---|
| Printer | Bambu Lab A1 |
| Trigger | Bambu Lab Timelapse Camera Trigger (CyberBrick) |
| Capture controller | Raspberry Pi 3B, Raspberry Pi OS Lite |
| Camera | Nikon D40 DSLR, USB-connected |
| Power | Dummy AC battery adapter (future) |

### 2.1 Hardware Notes from Research

**Nikon D40 + gphoto2:** True `--capture-tethered` mode is unreliable on the
D40 (known PTP property errors, lock-up reports). The system must use
`gphoto2 --capture-image-and-download` per trigger instead of event-based
tethering. The python-gphoto2 SWIG bindings are viable but the CLI is equally
reliable for per-shot capture on this body. **Decision: start with CLI
subprocess, abstract so bindings can replace it later.**

**Bambu Trigger output:** The CyberBrick Timelapse Trigger's wired 2.5mm output
mimics a standard camera remote-shutter cable — likely an open-drain /
relay-style short-to-ground pulse, not a logic-level GPIO signal. This means:

- The signal may need **pull-up resistor + optocoupler** or **voltage divider**
  to safely interface with the Pi's 3.3V GPIO.
- Community projects (e.g. `bodybybuddha/bbl-shutter-cam`) use Bluetooth
  `BBL_SHUTTER` as an alternative trigger method.
- **Decision: support both wired GPIO and Bluetooth trigger as pluggable
  `TriggerProvider` implementations.** Ship GPIO first; BLE trigger as fast-follow.

**RPi.GPIO debounce:** The built-in `bouncetime` parameter is unreliable with
mechanical/relay signals. Implement software debounce with pin-state re-check
inside the callback, and document hardware RC filter as recommended.

---

## 3. Design Principles

Priority order (never trade a higher for a lower):

1. **Reliability** — runs unattended for months
2. **Recoverability** — survives power loss, crashes, hangs at any point
3. **Simplicity** — no clever tricks; obvious code
4. **Image quality** — full DSLR resolution, proper exposure
5. **Performance** — fast enough, not optimized beyond need

---

## 4. Architecture

### 4.1 Responsibility Split

The **Raspberry Pi** owns the entire capture-to-upload pipeline:

- Listen for trigger pulses
- Control the DSLR
- Store frames locally
- Compile video
- Upload
- Verify + cleanup

The **printer monitoring service** (runs elsewhere — Proxmox, Docker, wherever)
sends exactly four events to the Pi:

| Event | Meaning |
|---|---|
| `print_started` | New print job detected, includes job metadata |
| `print_completed` | Print finished successfully |
| `print_cancelled` | User cancelled the print |
| `print_failed` | Print failed (error, runaway, etc.) |

Everything else is the Pi's problem.

### 4.2 Communication

Pi exposes a lightweight HTTP endpoint to receive print events.
Alternatively, it can poll or subscribe via MQTT. The transport is behind
the `PrinterProvider` interface — the daemon doesn't care how events arrive.

### 4.3 Component Diagram

```
┌─────────────────────────────────────────────────────┐
│                   Raspberry Pi 3B                   │
│                                                     │
│  ┌──────────┐   ┌───────────┐   ┌───────────────┐  │
│  │ Trigger   │──▶│ Capture   │──▶│ State Machine │  │
│  │ Provider  │   │ Service   │   │               │  │
│  └──────────┘   └───────────┘   └───────┬───────┘  │
│                                         │           │
│  ┌──────────┐   ┌───────────┐   ┌───────▼───────┐  │
│  │ Camera    │◀──│ Printer   │   │ Pipeline      │  │
│  │ Service   │   │ Provider  │   │ Orchestrator  │  │
│  └──────────┘   └───────────┘   └───────┬───────┘  │
│                                         │           │
│                 ┌───────────┐   ┌───────▼───────┐  │
│                 │ Compiler  │◀──│ Uploader      │  │
│                 │ (ffmpeg)  │   │ (pluggable)   │  │
│                 └───────────┘   └───────────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
         ▲                              │
         │ GPIO / BLE                   │ HTTP/S
         │                              ▼
   ┌─────┴──────┐              ┌──────────────┐
   │ Bambu A1   │              │ Appwrite     │
   │ + Trigger  │              │ (or NAS/S3)  │
   └────────────┘              └──────────────┘

         ▲
         │ MQTT / HTTP / WS
         │
   ┌─────┴──────────────┐
   │ Print Monitor      │
   │ (Proxmox/Docker)   │
   └────────────────────┘
```

---

## 5. State Machine

### 5.1 Normal Flow

```
IDLE
 │
 ▼  (print_started event received)
PRINT_STARTING
 │  • create job directory
 │  • initialize meta.json
 │  • verify camera ready
 ▼
CAPTURING
 │  • on each trigger pulse: capture frame, download, increment counter
 │  • update meta.json after each frame
 ▼  (print_completed event received)
COMPILING
 │  • run ffmpeg to produce output.mp4
 ▼
UPLOADING
 │  • upload output.mp4 via Uploader
 ▼
VERIFYING
 │  • confirm upload exists and is complete
 ▼
CLEANUP
 │  • delete frames/ and output.mp4
 │  • preserve meta.json and events.log
 ▼
IDLE
```

### 5.2 Error States

| State | Trigger | Recovery |
|---|---|---|
| `ERROR_CAMERA` | gphoto2 timeout/failure after retries | Log, retry on next trigger pulse; don't abort the job |
| `ERROR_COMPILE` | ffmpeg failure | Retry compilation; frames are preserved |
| `ERROR_UPLOAD` | Network failure, Appwrite error | Retry with backoff; video is preserved |
| `ERROR_STORAGE` | Disk full, write failure | Alert via log; pause capture until resolved |

### 5.3 Cancellation / Failure

On `print_cancelled` or `print_failed`:

- If in `CAPTURING`: stop accepting triggers, compile whatever frames exist
  (if > 0), proceed through upload/verify/cleanup as normal
- If in `COMPILING` or later: continue the pipeline to completion
- Record cancellation/failure reason in meta.json

### 5.4 Crash Recovery

On daemon startup:

1. Scan `prints/` for all job directories
2. Read each `meta.json` to determine last known state
3. Resume:
   - `CAPTURING` interrupted → mark as complete (we can't know where the print
     was), compile existing frames
   - `COMPILING` interrupted → re-run ffmpeg
   - `UPLOADING` interrupted → re-upload
   - `VERIFYING` interrupted → re-verify
   - `CLEANUP` interrupted → re-cleanup
4. Never delete frames that haven't been uploaded and verified

---

## 6. Interfaces

### 6.1 PrinterProvider

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PrintJob:
    job_id: str
    job_name: str
    printer_name: str
    started_at: datetime | None = None

class PrinterProvider(ABC):
    @abstractmethod
    def get_current_job(self) -> PrintJob | None: ...

    @abstractmethod
    def get_status(self) -> str: ...

    @abstractmethod
    def is_printing(self) -> bool: ...
```

Initial implementation: `HttpPrinterProvider` — receives POSTed events.

Future: `MqttPrinterProvider`, `BambuDirectProvider`, `HomeAssistantProvider`.

### 6.2 TriggerProvider

```python
class TriggerProvider(ABC):
    @abstractmethod
    def start(self, callback: Callable[[], None]) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
```

Initial: `GpioTriggerProvider` — edge detection on configurable pin with
software debounce.

Future: `BluetoothTriggerProvider` (BBL_SHUTTER BLE), `MqttTriggerProvider`.

### 6.3 CameraService

```python
class CameraService(ABC):
    @abstractmethod
    def capture_and_download(self, destination: Path) -> Path: ...

    @abstractmethod
    def is_ready(self) -> bool: ...
```

Initial: `GPhoto2Camera` — wraps CLI with subprocess, timeout, and retry logic.

Future: `GPhoto2NativeCamera` (python-gphoto2 bindings), `MockCamera` (testing).

### 6.4 Uploader

```python
@dataclass
class UploadResult:
    success: bool
    file_id: str | None = None
    metadata: dict | None = None
    verified: bool = False

class Uploader(ABC):
    @abstractmethod
    def upload(self, file_path: Path, metadata: dict) -> UploadResult: ...

    @abstractmethod
    def verify(self, file_id: str) -> bool: ...
```

Initial: `AppwriteUploader`.

Future: `NasUploader`, `S3Uploader`, `BackblazeUploader`, `SmbUploader`.

### 6.5 Compiler

```python
class Compiler(ABC):
    @abstractmethod
    def compile(self, frames_dir: Path, output_path: Path,
                fps: int = 30) -> bool: ...
```

Initial: `FfmpegCompiler` — H.264, yuv420p, configurable FPS.

---

## 7. Capture Pipeline

### 7.1 Directory Structure Per Job

```
prints/
  <job_id>/
    frames/
      frame-000001.jpg
      frame-000002.jpg
      frame-000003.jpg
      ...
    meta.json
    events.log
    output.mp4          (created during COMPILING)
```

### 7.2 meta.json

```json
{
  "job_id": "abc123",
  "job_name": "benchy",
  "printer_name": "bambu-a1",
  "camera": "nikon-d40",
  "started_at": "2026-07-26T14:30:00Z",
  "completed_at": null,
  "state": "CAPTURING",
  "frame_count": 47,
  "upload_status": null,
  "upload_file_id": null,
  "cancelled": false,
  "failed": false,
  "failure_reason": null,
  "video_fps": 30,
  "video_compiled": false
}
```

Updated atomically (write-tmp-then-rename) after every state change and every
captured frame.

### 7.3 Frame Naming

`frame-NNNNNN.jpg` — zero-padded to 6 digits. Sequential, never skipped
intentionally. If a capture fails, the counter does not increment.

### 7.4 Camera Capture Flow

```
trigger pulse received
  → debounce check (ignore if < MIN_INTERVAL since last)
  → check state == CAPTURING
  → call camera.capture_and_download(frames_dir / next_filename)
  → on success: increment frame_count, update meta.json
  → on failure: log error, retry up to N times
  → on timeout: kill gphoto2 process, log ERROR_CAMERA
  → never block the trigger listener
```

Camera capture runs in a worker thread/queue. If a trigger arrives while a
capture is in progress, queue it (up to a small buffer). Never drop the daemon's
main loop.

---

## 8. Video Compilation

Triggered when state transitions to `COMPILING`.

```bash
ffmpeg -framerate 30 -i frames/frame-%06d.jpg \
  -c:v libx264 -pix_fmt yuv420p \
  -movflags +faststart \
  output.mp4
```

- FPS configurable (default 30)
- `-movflags +faststart` for streaming-friendly output
- If fewer than 2 frames exist, skip compilation and log warning
- On Pi 3B this will be slow for large prints — that's acceptable

---

## 9. Upload + Verification

### 9.1 Upload Flow

1. Upload `output.mp4` to configured backend
2. Include metadata: job name, frame count, duration, timestamps
3. On failure: retry with exponential backoff (3 attempts, 5s/15s/45s)
4. On success: proceed to verification

### 9.2 Verification

1. Query the backend to confirm the file exists
2. Optionally compare file size
3. On success: mark `upload_status: "verified"` in meta.json
4. On failure: retry upload

### 9.3 Cleanup

Only after verification succeeds:

1. Delete `frames/` directory
2. Delete `output.mp4`
3. Keep `meta.json` (permanent record)
4. Keep `events.log` (permanent record)

Future: configurable retention period before deleting meta/logs.

---

## 10. Configuration

`config/config.yaml`:

```yaml
# Trigger
trigger:
  type: gpio            # gpio | bluetooth | mqtt
  gpio_pin: 17
  edge: rising          # rising | falling
  debounce_ms: 200

# Camera
camera:
  type: gphoto2_cli     # gphoto2_cli | gphoto2_native | mock
  timeout_seconds: 30
  retries: 3
  retry_delay_seconds: 2

# Capture
capture:
  base_dir: ./prints
  frame_format: "frame-{:06d}.jpg"

# Compilation
compile:
  fps: 30
  codec: libx264
  pixel_format: yuv420p

# Upload
upload:
  backend: appwrite     # appwrite | s3 | nas | none
  appwrite:
    endpoint: ${APPWRITE_ENDPOINT}
    project_id: ${APPWRITE_PROJECT_ID}
    api_key: ${APPWRITE_API_KEY}
    bucket_id: ${APPWRITE_BUCKET_ID}
  retry_attempts: 3
  retry_backoff_seconds: [5, 15, 45]

# Cleanup
cleanup:
  enabled: true
  delete_frames: true
  delete_video: true
  keep_meta: true
  keep_logs: true

# Logging
logging:
  level: INFO           # DEBUG | INFO | WARNING | ERROR
  format: json
  file: ./logs/bambucam.log

# Printer
printer:
  provider: http        # http | mqtt | mock
  http:
    listen_port: 8420
```

Secrets via environment variables; config references them with `${VAR}` syntax.

---

## 11. Logging

Structured JSON, one event per line.

```json
{
  "timestamp": "2026-07-26T14:30:01.234Z",
  "level": "INFO",
  "event": "FRAME_CAPTURED",
  "job_id": "abc123",
  "frame": 47,
  "message": "Captured frame-000047.jpg in 2.3s"
}
```

Event types:

| Event | When |
|---|---|
| `DAEMON_STARTED` | Daemon boots |
| `RECOVERY_STARTED` | Unfinished jobs found on startup |
| `PRINT_STARTED` | Print event received |
| `CAMERA_READY` | Camera check passed |
| `CAMERA_ERROR` | Camera check/capture failed |
| `TRIGGER_RECEIVED` | GPIO/BLE pulse detected |
| `FRAME_CAPTURED` | Image successfully saved |
| `FRAME_FAILED` | Capture failed after retries |
| `PRINT_COMPLETED` | Completion event received |
| `PRINT_CANCELLED` | Cancellation event received |
| `COMPILE_STARTED` | ffmpeg kicked off |
| `COMPILE_COMPLETED` | Video ready |
| `COMPILE_FAILED` | ffmpeg error |
| `UPLOAD_STARTED` | Upload initiated |
| `UPLOAD_COMPLETED` | Upload succeeded |
| `UPLOAD_FAILED` | Upload failed after retries |
| `VERIFY_SUCCESS` | Upload verified |
| `VERIFY_FAILED` | Verification failed |
| `CLEANUP_COMPLETED` | Local files removed |
| `STATE_CHANGED` | State machine transition |

---

## 12. Project Layout

```
bambucam/
├── config/
│   └── config.yaml.example
├── bambucam/
│   ├── __init__.py
│   ├── daemon.py              # Entry point, systemd-friendly
│   ├── state_machine.py       # State enum, transitions, persistence
│   ├── orchestrator.py        # Pipeline coordinator
│   ├── models.py              # PrintJob, UploadResult, JobMeta dataclasses
│   ├── camera/
│   │   ├── __init__.py
│   │   ├── base.py            # CameraService ABC
│   │   └── gphoto2.py         # GPhoto2Camera implementation
│   ├── trigger/
│   │   ├── __init__.py
│   │   ├── base.py            # TriggerProvider ABC
│   │   └── gpio.py            # GpioTriggerProvider
│   ├── printer/
│   │   ├── __init__.py
│   │   ├── base.py            # PrinterProvider ABC
│   │   └── http.py            # HttpPrinterProvider (receives POSTs)
│   ├── compiler/
│   │   ├── __init__.py
│   │   ├── base.py            # Compiler ABC
│   │   └── ffmpeg.py          # FfmpegCompiler
│   ├── upload/
│   │   ├── __init__.py
│   │   ├── base.py            # Uploader ABC
│   │   └── appwrite.py        # AppwriteUploader
│   ├── config.py              # YAML loader, env var substitution
│   └── logging.py             # Structured JSON logger setup
├── scripts/
│   ├── test_camera.py         # Camera connectivity test
│   ├── test_gpio.py           # GPIO trigger test
│   └── test_upload.py         # Appwrite upload test
├── systemd/
│   └── bambucam.service
├── tests/
│   └── ...
├── prints/                    # Created at runtime
├── logs/                      # Created at runtime
├── requirements.txt
├── pyproject.toml
├── SPEC.md
└── README.md
```

---

## 13. Dependencies

```
# Core
pyyaml
requests

# Camera
# (gphoto2 CLI installed via apt, not pip)

# GPIO
RPi.GPIO

# Video
# (ffmpeg installed via apt, not pip)

# Upload
appwrite

# Dev/Test
pytest
pytest-mock
```

System packages (apt): `gphoto2 libgphoto2-dev ffmpeg`

---

## 14. systemd Service

```ini
[Unit]
Description=BambuCam Timelapse Daemon
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/bambucam
ExecStart=/opt/bambucam/venv/bin/python -m bambucam.daemon
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/opt/bambucam/.env

[Install]
WantedBy=multi-user.target
```

---

## 15. Future Extension Points

These are not built initially but the architecture accommodates them:

| Feature | Extension Point |
|---|---|
| Multi-camera | Multiple `CameraService` instances |
| RAW capture | `CameraService.capture_raw()` method |
| Bluetooth trigger | `BluetoothTriggerProvider` |
| NAS/S3/Backblaze upload | Additional `Uploader` implementations |
| MQTT print detection | `MqttPrinterProvider` |
| Home Assistant integration | `HomeAssistantPrinterProvider` |
| Web dashboard | REST API layer over orchestrator state |
| Notifications (Discord/Slack) | Event hooks on state transitions |
| Metadata overlays | Post-processing step before compilation |
| WLED lighting sync | Event hooks on state transitions |
| Multiple printers | Multiple orchestrator instances |
| Timelapse presets | Compiler configuration profiles |
| AI thumbnail selection | Post-compile analysis step |

---

## 16. Implementation Plan

### Phase 1 — Foundation
1. Project scaffolding (pyproject.toml, package structure, config loader)
2. Models and state machine
3. Structured logging
4. Configuration system with env var substitution

### Phase 2 — Camera + Trigger
5. CameraService ABC + GPhoto2Camera (CLI subprocess)
6. TriggerProvider ABC + GpioTriggerProvider
7. Camera test utility
8. GPIO test utility

### Phase 3 — Pipeline
9. Orchestrator (coordinates state machine + services)
10. Capture pipeline (trigger → capture → store → update meta)
11. FfmpegCompiler
12. Crash recovery logic

### Phase 4 — Upload + Cleanup
13. Uploader ABC + AppwriteUploader
14. Verification logic
15. Cleanup logic
16. Upload test utility

### Phase 5 — Production
17. Daemon entry point
18. systemd service
19. README + installation guide
20. Sample config
21. End-to-end testing with MockCamera + MockTrigger

---

## 17. Open Questions (Resolved)

1. **Trigger voltage:** TBD — will measure physically. Design the GPIO trigger
   with configurable pull-up/pull-down and document optocoupler option.

2. **Camera power management:** TBD — external power supply in progress (dummy
   battery adapter). Add keep-alive/wake handling to CameraService as needed.

3. **Print event source:** No specific software committed. Build the generic
   `HttpPrinterProvider` first — any monitoring tool can POST events to it.

4. **Storage budget:** 128GB micro SD. At ~3MB/frame, that's ~40,000 frames
   (~200 prints at 200 layers) before space pressure. Cleanup after upload
   keeps this comfortable. NAS available for long-term archival.

5. **Upload retry policy:** 3 attempts with exponential backoff (5s/15s/45s).
   Log failure and preserve video locally on exhaustion.
