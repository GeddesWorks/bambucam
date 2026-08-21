from __future__ import annotations

import logging
from pathlib import Path

from bambucam.models import UploadResult
from bambucam.upload.base import Uploader

logger = logging.getLogger("bambucam")


class NoOpUploader(Uploader):
    """Upload backend that does nothing — for testing or local-only setups."""

    def upload(self, file_path: Path, metadata: dict) -> UploadResult:
        logger.info(
            "NoOp uploader: skipping upload of %s", file_path.name,
            extra={"event": "UPLOAD_SKIPPED"},
        )
        return UploadResult(success=True, file_id="local", verified=True)

    def verify(self, file_id: str) -> bool:
        return True
