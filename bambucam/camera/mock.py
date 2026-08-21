from __future__ import annotations

import logging
from pathlib import Path

from bambucam.camera.base import CameraService

logger = logging.getLogger("bambucam")


class MockCamera(CameraService):
    """Fake camera for testing — writes a minimal JPEG-like file."""

    def capture_and_download(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"\xff\xd8\xff\xe0mock-jpeg-data")
        logger.debug("MockCamera captured %s", destination.name,
                      extra={"event": "FRAME_CAPTURED"})
        return destination

    def is_ready(self) -> bool:
        return True
