#!/bin/bash
# BambuCam — Configure Bambuddy Outbound Webhook
#
# This script tells you how to set up Bambuddy to send print events
# to BambuCam's HTTP listener.
#
# Bambuddy webhooks are configured through its web UI, not via API.
# This script prints the instructions.

PI_IP="${1:-192.168.1.209}"
PI_PORT="${2:-8420}"

cat << EOF
=== Bambuddy Webhook Setup for BambuCam ===

Open Bambuddy's web UI and configure an outbound webhook notification:

1. Go to: Settings → Notifications
2. Click "Add Notification Provider"
3. Configure:

   Type:           Webhook
   Name:           BambuCam Timelapse
   URL:            http://${PI_IP}:${PI_PORT}/
   Payload Format: Generic (not Slack)
   Auth Header:    (leave blank — BambuCam doesn't require auth)

4. Enable these event toggles:
   ✓ Print Start     (on_print_start)
   ✓ Print Complete  (on_print_complete)
   ✓ Print Failed    (on_print_failed)
   ✓ Print Stopped   (on_print_stopped)

   Leave all other events OFF (AMS, humidity, queue, etc.)

5. Save the notification provider.

=== Testing ===

Once configured, you can verify BambuCam receives events:

  # On the Pi, check the listener is running:
  curl http://${PI_IP}:${PI_PORT}/health

  # Or send a test event manually:
  curl -X POST http://${PI_IP}:${PI_PORT}/ \\
    -H "Content-Type: application/json" \\
    -d '{
      "source": "Bambuddy",
      "event": "print_start",
      "printer": "Jeff",
      "filename": "test-benchy.gcode",
      "timestamp": "2026-01-01T00:00:00"
    }'

=== Bambuddy Webhook Payload (for reference) ===

Bambuddy sends JSON like this on print events:

  {
    "title": "Print Started",
    "message": "benchy.gcode started on Jeff",
    "timestamp": "2026-08-21T14:30:00.000",
    "source": "Bambuddy",
    "event": "print_start",        ← BambuCam maps this
    "printer": "Jeff",
    "filename": "benchy.gcode",
    "duration": "0h 0m",
    "progress": "0"
  }

BambuCam automatically detects Bambuddy payloads and maps events:
  print_start   → print_started
  print_complete → print_completed
  print_failed  → print_failed
  print_stopped → print_cancelled

EOF
