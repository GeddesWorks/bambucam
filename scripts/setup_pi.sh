#!/bin/bash
# BambuCam — Raspberry Pi Setup Script
# Run as: sudo bash setup_pi.sh
#
# This installs all dependencies, creates the project directory,
# sets up the Python environment, and installs the systemd service.

set -euo pipefail

INSTALL_DIR="/opt/bambucam"
SERVICE_USER="collin"
REPO_URL="https://github.com/GeddesWorks/bambucam.git"
BRANCH="claude/new-project-spec-023uvp"

echo "=== BambuCam Pi Setup ==="

# System packages
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    gphoto2 libgphoto2-dev \
    ffmpeg \
    git \
    jq curl

# Disable gphoto2 auto-mount (conflicts with tethered capture)
echo "[2/7] Disabling gphoto2 auto-mount..."
if [ -f /usr/lib/udev/rules.d/60-gphoto2.rules ]; then
    echo "# Disabled for BambuCam tethered capture" > /etc/udev/rules.d/60-gphoto2.rules
    udevadm control --reload-rules
fi
# Also kill any gvfs-gphoto2 processes that may grab the camera
systemctl mask gvfs-gphoto2-volume-monitor.service 2>/dev/null || true

# Clone repo
echo "[3/7] Cloning BambuCam..."
if [ -d "$INSTALL_DIR" ]; then
    echo "  $INSTALL_DIR exists, pulling latest..."
    cd "$INSTALL_DIR"
    git fetch origin "$BRANCH"
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Python environment
echo "[4/7] Setting up Python virtual environment..."
# --system-site-packages so the venv can see Debian's python3-rpi-lgpio,
# which is the only GPIO library that actually works on current images.
python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -e ".[dev]" -q

# GPIO library for the CyberBrick trigger.
#
# Legacy RPi.GPIO imports and reads pins fine on current Raspberry Pi OS but
# add_event_detect() raises "Failed to add edge detection" — which is exactly
# what GpioTriggerProvider needs, so the trigger silently never fires. Use
# rpi-lgpio (a drop-in providing the RPi.GPIO API on top of lgpio) instead.
#
# Prefer Debian's python3-rpi-lgpio: pip's rpi-lgpio has to build lgpio from
# source, which needs swig and fails on a stock image.
echo "  Installing GPIO library..."
apt-get install -y -qq python3-rpi-lgpio 2>/dev/null || true

# Legacy RPi.GPIO inside the venv would shadow the system rpi-lgpio.
"$INSTALL_DIR/venv/bin/pip" uninstall -y RPi.GPIO -q 2>/dev/null || true

if ! "$INSTALL_DIR/venv/bin/python" -c "import RPi.GPIO" 2>/dev/null; then
    "$INSTALL_DIR/venv/bin/pip" install rpi-lgpio -q 2>/dev/null || true
fi

# Import is not enough — confirm edge detection actually works.
if "$INSTALL_DIR/venv/bin/python" - <<'GPIOCHECK' 2>/dev/null
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.add_event_detect(17, GPIO.FALLING, callback=lambda c: None, bouncetime=200)
GPIO.remove_event_detect(17)
GPIO.cleanup()
GPIOCHECK
then
    echo "  GPIO edge detection verified."
else
    echo "  WARNING: GPIO edge detection is not working."
    echo "           The daemon will run but the trigger will never fire."
    echo "           Try: sudo apt-get install python3-rpi-lgpio"
fi

# Create runtime directories
echo "[5/7] Creating runtime directories..."
mkdir -p "$INSTALL_DIR/prints"
mkdir -p "$INSTALL_DIR/logs"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# Config file
echo "[6/7] Setting up configuration..."
if [ ! -f "$INSTALL_DIR/config/config.yaml" ]; then
    cp "$INSTALL_DIR/config/config.yaml.example" "$INSTALL_DIR/config/config.yaml"
    echo "  Created config/config.yaml — edit with your settings"
else
    echo "  config/config.yaml already exists, keeping it"
fi

# .env file for secrets
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cat > "$INSTALL_DIR/.env" << 'ENVEOF'
# BambuCam environment variables
# Fill in your Appwrite credentials
APPWRITE_ENDPOINT=
APPWRITE_PROJECT_ID=
APPWRITE_API_KEY=
APPWRITE_BUCKET_ID=

# Bambuddy API key
BAMBUDDY_API_KEY=
ENVEOF
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    echo "  Created .env — fill in your secrets"
else
    echo "  .env already exists, keeping it"
fi

# systemd service
echo "[7/7] Installing systemd service..."
cp "$INSTALL_DIR/systemd/bambucam.service" /etc/systemd/system/
sed -i "s/User=pi/User=$SERVICE_USER/" /etc/systemd/system/bambucam.service
systemctl daemon-reload
systemctl enable bambucam.service
echo "  Service installed (not started yet — configure first)"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $INSTALL_DIR/.env with your Appwrite credentials"
echo "  2. Edit $INSTALL_DIR/config/config.yaml if needed"
echo "  3. Connect the Nikon D40 via USB"
echo "  4. Test camera: $INSTALL_DIR/venv/bin/python $INSTALL_DIR/scripts/test_camera.py"
echo "  5. Start: sudo systemctl start bambucam"
echo "  6. Logs: journalctl -u bambucam -f"
