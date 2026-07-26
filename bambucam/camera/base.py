from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class CameraService(ABC):
    @abstractmethod
    def capture_and_download(self, destination: Path) -> Path:
        """Capture a still image and save it to destination. Returns the path."""
        ...

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if the camera is connected and responsive."""
        ...
