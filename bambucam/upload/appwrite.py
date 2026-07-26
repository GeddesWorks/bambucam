from __future__ import annotations

import logging
from pathlib import Path

from appwrite.client import Client
from appwrite.input_file import InputFile
from appwrite.services.storage import Storage

from bambucam.models import UploadResult
from bambucam.upload.base import Uploader

logger = logging.getLogger("bambucam")


class AppwriteUploader(Uploader):
    def __init__(self, endpoint: str, project_id: str, api_key: str,
                 bucket_id: str):
        self._bucket_id = bucket_id
        self._client = Client()
        self._client.set_endpoint(endpoint)
        self._client.set_project(project_id)
        self._client.set_key(api_key)
        self._storage = Storage(self._client)

    def upload(self, file_path: Path, metadata: dict) -> UploadResult:
        try:
            result = self._storage.create_file(
                bucket_id=self._bucket_id,
                file_id="unique()",
                file=InputFile.from_path(str(file_path)),
            )
            file_id = result["$id"]
            logger.info(
                "Uploaded %s as %s", file_path.name, file_id,
                extra={"event": "UPLOAD_COMPLETED", "file_id": file_id},
            )
            return UploadResult(
                success=True,
                file_id=file_id,
                metadata={"name": file_path.name, **metadata},
            )
        except Exception as e:
            logger.error(
                "Upload failed: %s", e,
                extra={"event": "UPLOAD_FAILED"},
            )
            return UploadResult(success=False)

    def verify(self, file_id: str) -> bool:
        try:
            result = self._storage.get_file(
                bucket_id=self._bucket_id,
                file_id=file_id,
            )
            return result.get("$id") == file_id
        except Exception:
            return False
