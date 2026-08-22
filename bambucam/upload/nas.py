from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from bambucam.models import UploadResult, slugify_job_name
from bambucam.upload.base import Uploader

logger = logging.getLogger("bambucam")

_JOB_TIMESTAMP = re.compile(r"-(\d{9,11})$")


class NasUploader(Uploader):
    """Archive the finished video to a mounted network share.

    The share is a mount point, not a filesystem we own, so treat it as
    something that can vanish: if the mount is gone, fail loudly rather than
    silently filling the Pi's SD card with files written to an empty directory
    where the share should be.
    """

    def __init__(self, base_dir: str = "/mnt/nas/BambuCam",
                 mount_point: str = "/mnt/nas",
                 mount_check: bool = True):
        self._base = Path(base_dir)
        self._mount_point = Path(mount_point)
        self._mount_check = mount_check

    def _assert_mounted(self) -> None:
        """A missing share looks like an ordinary empty directory.

        Check the configured mount point explicitly. Inferring it by walking
        ancestors for "some mount point" does not work: '/' always qualifies,
        and on this Pi so does '/tmp', so the check would pass on paths that
        are nowhere near the share.
        """
        if not self._mount_check:
            return
        if not os.path.ismount(self._mount_point):
            raise RuntimeError(
                f"{self._mount_point} is not mounted — refusing to archive "
                "(writing here would fill the local disk instead of the NAS)"
            )

    @staticmethod
    def _job_datetime(metadata: dict, file_path: Path) -> datetime:
        """Print start time, falling back to when the video was written."""
        match = _JOB_TIMESTAMP.search(metadata.get("job_id", "") or "")
        if match:
            try:
                return datetime.fromtimestamp(int(match.group(1)))
            except (ValueError, OSError, OverflowError):
                pass
        return datetime.fromtimestamp(file_path.stat().st_mtime)

    def _destination(self, file_path: Path, metadata: dict) -> Path:
        when = self._job_datetime(metadata, file_path)
        # The model name beats the filename, which Bambu Studio derives from
        # slicer settings ("0.2mm layer, 2 walls, 15% infill") unless renamed.
        print_name = (metadata.get("print_name") or "").strip()
        if print_name:
            slug = slugify_job_name(print_name)
        else:
            slug = _JOB_TIMESTAMP.sub("", metadata.get("job_id", "print")) or "print"
        name = f"{when:%Y-%m-%d_%H%M}_{slug}{file_path.suffix}"

        target_dir = self._base / f"{when:%Y}"
        dest = target_dir / name

        # Never overwrite an existing archive; two prints can share a minute.
        counter = 2
        while dest.exists():
            dest = target_dir / f"{when:%Y-%m-%d_%H%M}_{slug}-{counter}{file_path.suffix}"
            counter += 1
        return dest

    def upload(self, file_path: Path, metadata: dict) -> UploadResult:
        try:
            self._assert_mounted()
            dest = self._destination(file_path, metadata)
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Copy to a temp name first so an interrupted transfer never leaves
            # a truncated file that looks like a finished archive.
            staging = dest.with_name(f".{dest.name}.part")
            shutil.copyfile(file_path, staging)

            source_size = file_path.stat().st_size
            staged_size = staging.stat().st_size
            if staged_size != source_size:
                staging.unlink(missing_ok=True)
                raise RuntimeError(
                    f"short write: {staged_size} of {source_size} bytes"
                )

            os.replace(staging, dest)
            logger.info(
                "Archived %s to %s (%.1f MB)",
                file_path.name, dest, source_size / 1_048_576,
                extra={"event": "UPLOAD_COMPLETED"},
            )
            return UploadResult(success=True, file_id=str(dest),
                                metadata={"size": source_size})
        except (OSError, RuntimeError) as e:
            logger.error("NAS archive failed: %s", e,
                         extra={"event": "UPLOAD_FAILED"})
            return UploadResult(success=False, file_id=None)

    def verify(self, file_id: str) -> bool:
        try:
            path = Path(file_id)
            ok = path.is_file() and path.stat().st_size > 0
            if not ok:
                logger.error("Verify failed: %s missing or empty", file_id,
                             extra={"event": "VERIFY_FAILED"})
            return ok
        except OSError as e:
            logger.error("Verify failed: %s", e, extra={"event": "VERIFY_FAILED"})
            return False
