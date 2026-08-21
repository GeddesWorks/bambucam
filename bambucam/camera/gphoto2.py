from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from bambucam.camera.base import CameraService

logger = logging.getLogger("bambucam")

_JPEG_MAGIC = bytes.fromhex("ffd8ff")  # SOI + start of first marker


class GPhoto2Camera(CameraService):
    def __init__(self, timeout: int = 30, retries: int = 3,
                 retry_delay: float = 2.0):
        self._timeout = timeout
        self._retries = retries
        self._retry_delay = retry_delay

    def capture_and_download(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None

        for attempt in range(1, self._retries + 1):
            try:
                result = subprocess.run(
                    [
                        "gphoto2",
                        "--capture-image-and-download",
                        "--filename", str(destination),
                        "--force-overwrite",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
                if result.returncode == 0 and destination.exists():
                    self._assert_jpeg(destination)
                    return destination
                last_error = RuntimeError(
                    f"gphoto2 returned {result.returncode}: {result.stderr.strip()}"
                )
            except subprocess.TimeoutExpired:
                self._kill_gphoto2()
                last_error = TimeoutError(
                    f"gphoto2 timed out after {self._timeout}s"
                )
            except OSError as e:
                last_error = e

            if attempt < self._retries:
                logger.warning(
                    "Capture attempt %d/%d failed: %s",
                    attempt, self._retries, last_error,
                    extra={"event": "CAPTURE_RETRY"},
                )
                time.sleep(self._retry_delay)

        raise RuntimeError(f"Capture failed after {self._retries} attempts") from last_error

    @staticmethod
    def _assert_jpeg(path: Path) -> None:
        """Fail fast if the camera handed us something ffmpeg cannot compile.

        gphoto2 writes whatever the camera shot to --filename regardless of
        extension, so a camera set to NEF/RAW produces RAW bytes named .jpg.
        Every capture then "succeeds" and the job only dies in COMPILING, long
        after the print finished and with no frames worth keeping.
        """
        with path.open("rb") as f:
            magic = f.read(3)
        if magic != _JPEG_MAGIC:
            path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Camera returned a non-JPEG file (magic bytes {magic.hex()}). "
                "Set the camera's image quality to JPEG — RAW/NEF frames "
                "cannot be compiled into a timelapse."
            )

    def is_ready(self) -> bool:
        try:
            result = subprocess.run(
                ["gphoto2", "--auto-detect"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and "nikon" in result.stdout.lower()
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _kill_gphoto2(self) -> None:
        try:
            subprocess.run(["pkill", "-f", "gphoto2"], timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
