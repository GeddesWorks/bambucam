from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from bambucam.models import UploadResult


class Uploader(ABC):
    @abstractmethod
    def upload(self, file_path: Path, metadata: dict) -> UploadResult:
        """Upload a file. Returns UploadResult with status and file_id."""
        ...

    @abstractmethod
    def verify(self, file_id: str) -> bool:
        """Verify an uploaded file exists and is complete."""
        ...
