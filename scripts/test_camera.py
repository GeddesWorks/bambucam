#!/usr/bin/env python3
"""Test camera connectivity and capture."""

import sys
from pathlib import Path

from bambucam.camera.gphoto2 import GPhoto2Camera


def main() -> None:
    camera = GPhoto2Camera(timeout=30, retries=1)

    print("Checking camera...")
    if not camera.is_ready():
        print("ERROR: Camera not detected. Check USB connection.")
        sys.exit(1)

    print("Camera detected.")
    dest = Path("test_capture.jpg")
    print(f"Attempting capture → {dest}")

    try:
        result = camera.capture_and_download(dest)
        size_kb = result.stat().st_size / 1024
        print(f"Success! Captured {result.name} ({size_kb:.0f} KB)")
    except Exception as e:
        print(f"Capture failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
