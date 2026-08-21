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
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -e ".[dev]" -q

# GPIO library for the CyberBrick trigger. rpi-lgpio is the drop-in
# RPi.GPIO replacement that works on current Raspberry Pi OS (Bookworm and
# later); fall back to legacy RPi.GPIO on older images. Without one of these
# the daemon starts but logs TRIGGER_UNAVAILABLE and captures nothing.
echo "  Installing GPIO library..."
if ! "$INSTALL_DIR/venv/bin/pip" install rpi-lgpio -q 2>/dev/null; then
    if ! "$INSTALL_DIR/venv/bin/pip" install RPi.GPIO -q 2>/dev/null; then
        echo "  WARNING: no GPIO library installed — the GPIO trigger will not work."
        echo "           Install rpi-lgpio or RPi.GPIO manually before wiring the trigger."
    fi
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
