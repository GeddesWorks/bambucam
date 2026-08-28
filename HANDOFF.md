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
| Nikon D40 capture | Done — 2.4s per frame |
| First real print | Partial — camera battery died at frame 13 |
| Fully unattended run | **Done** — 40 layers, then 401 layers, 0 dropped frames |
| Archive to NAS | Done — verified end to end |

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
shutterspeed 1/8   f/8   iso 400   expprogram M
```

**Do not shoot wide open.** f/3.5 was chosen to scrape light out of a dark
room and it cost real sharpness: the scene spans depth (near plate edge to far
edge, plus the print growing toward the camera) and at f/3.5 only a thin slice
is in focus. Measured on the same scene at matched brightness, edge energy more
than doubled going to f/8:

| Aperture | Edge energy |
|---|---|
| f/3.5 | 1.56 |
| f/8   | 3.33 |

With a 2s dwell there is room to pay for it with shutter speed instead of
aperture or ISO. 1/8s is 125ms; the shutter fires 0-1s after the trigger, so
the exposure ends by ~1.1s, comfortably inside the dwell.

**The viewfinder cannot be trusted for focus.** The D40's pentamirror finder is
small and dim; softness that is obvious at 100% in a 6MP file is invisible in
it. Judge focus from a captured frame cropped 1:1, never from the viewfinder.
A useful sharpness proxy without eyeballing:

```bash
ffprobe -v error -f lavfi "movie=FRAME.jpg,format=gray,convolution=0 -1 0 -1 4 -1 0 -1 0,signalstats"   -show_entries frame_tags=lavfi.signalstats.YAVG -of csv=p=0
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

### Archiving to the NAS — working

Finished videos are archived to the `media` share on **192.168.1.54**, which
allows **anonymous/guest** access, so there are no credentials anywhere.

```
//192.168.1.54/media /mnt/nas cifs guest,uid=1000,gid=1000,vers=3.0,file_mode=0664,dir_mode=0775,_netdev,nofail,x-systemd.automount,x-systemd.idle-timeout=600 0 0
```

**`x-systemd.automount` is load-bearing, not decoration.** A plain cifs mount
that drops never comes back on its own. It happened: the share went away with
no reboot, a 509-frame print captured and compiled fine, then failed to upload
three times and sat in `ERROR_UPLOAD` until someone noticed the video was
missing a day later. With automount, the next access re-mounts the share —
verified by unmounting and watching a directory listing bring it back.

Nothing was lost, because the guard refused to write to an unmounted path
rather than filling the SD card with a file nobody would find, and a daemon
restart recovered the job straight through upload, verify and cleanup.

Automount changes what the guard must check: the mount point always satisfies
`os.path.ismount` once autofs is in place, even with the NAS unreachable. The
uploader now touches the path first (triggering the mount) and then requires a
real filesystem in `/proc/self/mounts`, rejecting the autofs stub.

That line is in `/etc/fstab`; `_netdev,nofail` means a NAS outage delays nothing
at boot. Requires `cifs-utils` (and `smbclient` for listing shares).

Files land as `BambuCam/<year>/<YYYY-MM-DD_HHMM>_<job-slug>.mp4`, dated from the
print start rather than the upload so archives sort chronologically. Verified:
a real 4.6 MB video copied with a matching md5, and a full pipeline run
archived, verified, and cleaned up with `meta.json` retaining `upload_file_id`.

Two failure modes the uploader defends against, both worth keeping:

- **An unmounted share looks like an ordinary empty directory.** Writing blindly
  would fill the Pi's SD card while appearing to succeed, so `mount_check`
  refuses unless the configured `mount_point` is genuinely mounted. Check the
  mount point explicitly — walking ancestors for "some mount point" passes on
  `/` everywhere and on `/tmp` on this Pi, guarding nothing.
- **An interrupted copy would leave a truncated file that looks complete.** The
  copy goes to a dotfile and is renamed into place, and never overwrites an
  existing archive when two prints share a minute.

Appwrite remains implemented but unconfigured; `.env` still has empty
credentials. The NAS backend supersedes it unless offsite copies are wanted.

**Cleanup is now enabled** and only runs after a verified upload. A verify
failure routes to `ERROR_UPLOAD`, preserving frames and video for the next
start to retry.

### Adding a config section

`config.upload.nas` crashed the daemon at startup with
`AttributeError: 'dict' object has no attribute 'dir'` because new nested
sections must be registered in `_NESTED_TYPES` in `bambucam/config.py` or they
load as plain dicts. Unit tests that construct a backend directly never catch
this — `tests/test_config_nested.py` now walks every nested dataclass field and
fails if one is unregistered.

## The unattended run that worked

2026-08-22, 40 layers: 40 frames captured (one per layer, no gaps, no
retries), compiled, archived to
`BambuCam/2026/2026-08-22_1634_0.2mm-layer-2-walls-7-infill.mp4`, verified,
and the frames cleaned off the Pi — with no intervention.

Camera settings for that run, with a `G4 P1000` layer-change dwell:

```
shutterspeed 1/60   f/3.5   iso 800   expprogram M
```

Sharp at 1/60 with the dwell in place. With `G4 P2000` the next step is
**1/30 at ISO 400**, two stops less noise, which matters a lot on a D40.

**Timelapse mode must be enabled in the slicer.** Without it the printer never
parks, the CyberBrick never fires, and you get a completed print with zero
frames — daemon healthy, log clean, nothing captured. A whole print was lost to
this. The symptom is identical to a wiring fault, so check the slicer setting
before touching the wiring; `scripts/probe_gpio.py` with the daemon stopped
shows no edges in either case.

**Plate luminance depends on what is on the plate.** An empty plate meters near
155 while a plate carrying dark parts meters near 115, at identical exposure.
Do not "correct" a bright early frame — the number falls on its own as the
print grows, and correcting makes every later frame too dark. Measure the crop,
then look at the image before changing anything.

## Video naming and length

Videos are named after the **model**, not the file: Bambu Studio names a
project after its slicer settings unless you rename it, which is why early
archives are called `0.2mm-layer-2-walls-15-infill`. Bambuddy's archive record
carries the real name in `print_name`, looked up at upload time by matching the
job name against the record's `filename`:

```
BambuCam/2026/2026-08-22_1739_Fidget-Slider-relaxation-in-your-hand.mp4
```

Best effort only — Bambuddy being down, a missing key, or no matching record
all fall back to the job slug rather than failing the upload. Needs
`BAMBUDDY_API_KEY` in `.env` and a `bambuddy:` section in config.

Frame rate adapts so video length does not scale with print height:

```yaml
compile:
  target_duration_seconds: 20   # 0 disables, keeping fixed fps
  min_fps: 6
  max_fps: 60
```

Measured: 40 frames -> 6 fps (6.7s, floored by min_fps), 243 -> 12 fps (20s),
900 -> 45 fps (20s), 2000 -> 60 fps (33s, capped). Without it, 900 layers at a
fixed 6 fps would be a two-and-a-half minute video.

**Adding a config section means editing two registries.** `_NESTED_TYPES`
turns a nested dict into a dataclass, and `_dict_to_config`'s `section_map`
decides whether a top-level section is read at all. Missing from the first, the
daemon crashes at startup; missing from the second, the section is silently
discarded and the feature never sees its settings — which is exactly how
`bambuddy.url` stayed empty while the YAML plainly set it. Both are covered by
`tests/test_config_nested.py` now.

## Encoding must stay inside 905MB

The Pi 3B has 905MB and **no swap**. x264 buffers `rc_lookahead` raw frames,
and a 3008x2000 frame is ~9MB, so a full-resolution encode of a long print
climbs to 2.2GB virtual and is killed:

```
enc0:0:libx264 invoked oom-killer
Out of memory: Killed process (ffmpeg) total-vm:2242144kB
```

A 401-frame print died this way after 57s with all 401 frames sitting fine on
disk. **Short prints hid it** — 13 and 40 frames never keep the lookahead full,
so every earlier compile succeeded and the ceiling went unnoticed until a real
print hit it.

Defaults now scale to 1920 wide, cap `rc-lookahead` at 10, disable
`sync-lookahead`, and limit threads to 2. Measured on the failed job: **147s
instead of a projected ~19 min**, because scaling cuts the work as well as the
memory. `scale_width: 0` restores native resolution if you ever move encoding
to a bigger machine.

The failed job recovered cleanly: it sat in `ERROR_COMPILE`, and a restart
resumed it, compiled, archived, verified, and cleaned up without losing a frame.

**Beware stale log matches when checking status.** Twice a watcher grepping the
last matching line reported an old failure as current — once blaming the camera
when the fault was elsewhere, once declaring a running compile dead. Filter on
the timestamp or watch a monotonic signal (the NAS file count) instead.

## Notes

- Video compilation on the Pi 3B will be slow (~5-10 min for 200 frames).
  Offloading to Proxmox via a `RemoteFfmpegCompiler` (rsync frames out, pull
  output.mp4 back) is the planned follow-up.
- `HttpPrinterProvider` does not filter on printer name; scoping is done in
  Bambuddy. If a second webhook source is ever added, add filtering here.
- EP-5 dummy battery for continuous camera power is on order.
