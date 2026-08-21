from __future__ import annotations

import base64
import logging
from pathlib import Path

from bambucam.camera.base import CameraService

logger = logging.getLogger("bambucam")

# A valid 64x64 grayscale baseline JPEG. Frames written by the mock camera have
# to survive ffmpeg compilation, so this needs to be a real decodable image
# rather than a placeholder byte string.
_MOCK_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzU5LjM3LjEwMAD/2wBDAAgYGBwYHCEhISEhISck"
    "JygoKCcnJycoKCgrKyszMzMrKysoKCsrMDAzMzc5NzQ0MzQ5OTw8PEhIRUVUVFdnZ3z/xABKAAEA"
    "AAAAAAAAAAAAAAAAAAAAAQEAAAAAAAAAAAAAAAAAAAAAEAEAAAAAAAAAAAAAAAAAAAAAEQEAAAAA"
    "AAAAAAAAAAAAAAAA/8AAEQgAQABAAwEiAAIRAAMRAP/aAAwDAQACEQMRAD8AAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAA/9k="
)


class MockCamera(CameraService):
    """Fake camera for testing — writes a valid placeholder JPEG."""

    def capture_and_download(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_MOCK_JPEG)
        logger.debug("MockCamera captured %s", destination.name,
                      extra={"event": "FRAME_CAPTURED"})
        return destination

    def is_ready(self) -> bool:
        return True
