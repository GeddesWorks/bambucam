from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class PrintJob:
    job_id: str
    job_name: str
    printer_name: str = ""
    started_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)


@dataclass
class JobMeta:
    job_id: str
    job_name: str
    printer_name: str
    camera: str
    started_at: str
    completed_at: str | None = None
    state: str = "PRINT_STARTING"
    frame_count: int = 0
    upload_status: str | None = None
    upload_file_id: str | None = None
    cancelled: bool = False
    failed: bool = False
    failure_reason: str | None = None
    video_fps: int = 30
    video_compiled: bool = False

    @classmethod
    def from_print_job(cls, job: PrintJob, camera: str = "nikon-d40",
                       fps: int = 30) -> JobMeta:
        return cls(
            job_id=job.job_id,
            job_name=job.job_name,
            printer_name=job.printer_name,
            camera=camera,
            started_at=job.started_at.isoformat() if job.started_at else "",
            video_fps=fps,
        )

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "printer_name": self.printer_name,
            "camera": self.camera,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "state": self.state,
            "frame_count": self.frame_count,
            "upload_status": self.upload_status,
            "upload_file_id": self.upload_file_id,
            "cancelled": self.cancelled,
            "failed": self.failed,
            "failure_reason": self.failure_reason,
            "video_fps": self.video_fps,
            "video_compiled": self.video_compiled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> JobMeta:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class UploadResult:
    success: bool
    file_id: str | None = None
    metadata: dict = field(default_factory=dict)
    verified: bool = False


@dataclass
class JobDirectory:
    root: Path
    frames_dir: Path
    meta_path: Path
    events_log_path: Path
    video_path: Path

    @classmethod
    def create(cls, base_dir: Path, job_id: str) -> JobDirectory:
        root = base_dir / job_id
        job_dir = cls(
            root=root,
            frames_dir=root / "frames",
            meta_path=root / "meta.json",
            events_log_path=root / "events.log",
            video_path=root / "output.mp4",
        )
        job_dir.frames_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def next_frame_path(self, frame_number: int) -> Path:
        return self.frames_dir / f"frame-{frame_number:06d}.jpg"

    def frame_count(self) -> int:
        return len(list(self.frames_dir.glob("frame-*.jpg")))
