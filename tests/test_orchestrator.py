import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bambucam.config import BambuCamConfig
from bambucam.models import PrintJob, UploadResult
from bambucam.orchestrator import Orchestrator
from bambucam.state_machine import State


class MockCamera:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.capture_count = 0

    def capture_and_download(self, destination):
        if self.should_fail:
            raise RuntimeError("Camera error")
        self.capture_count += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"\xff\xd8fake jpeg data")
        return destination

    def is_ready(self):
        return not self.should_fail


class MockCompiler:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.compile_count = 0

    def compile(self, frames_dir, output_path, fps=30):
        if self.should_fail:
            return False
        self.compile_count += 1
        output_path.write_bytes(b"fake mp4")
        return True


class MockUploader:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.upload_count = 0

    def upload(self, file_path, metadata):
        if self.should_fail:
            return UploadResult(success=False)
        self.upload_count += 1
        return UploadResult(success=True, file_id="file-001")

    def verify(self, file_id):
        return not self.should_fail


@pytest.fixture
def config(tmp_path):
    cfg = BambuCamConfig()
    cfg.capture.base_dir = str(tmp_path / "prints")
    cfg.cleanup.enabled = True
    return cfg


@pytest.fixture
def orch(config):
    return Orchestrator(
        config=config,
        camera=MockCamera(),
        compiler=MockCompiler(),
        uploader=MockUploader(),
    )


def test_starts_idle(orch):
    assert orch.state == State.IDLE


def test_print_start_transitions_to_capturing(orch):
    job = PrintJob(job_id="job1", job_name="benchy")
    orch.on_print_event("print_started", job)
    assert orch.state == State.CAPTURING
    assert orch.current_job is not None
    assert orch.current_job.job_id == "job1"


def test_capture_frame(orch):
    job = PrintJob(job_id="job1", job_name="benchy")
    orch.on_print_event("print_started", job)
    orch.on_trigger()
    time.sleep(0.5)
    assert orch.current_job.frame_count >= 1


def test_full_pipeline(orch, config):
    job = PrintJob(job_id="job1", job_name="benchy")
    orch.on_print_event("print_started", job)

    for _ in range(3):
        orch.on_trigger()
        time.sleep(0.3)

    orch.on_print_event("print_completed", None)
    time.sleep(2)

    assert orch.state == State.IDLE

    meta_path = Path(config.capture.base_dir) / "job1" / "meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["upload_status"] == "verified"
    assert meta["video_compiled"]


def test_ignores_trigger_when_idle(orch):
    orch.on_trigger()
    assert orch.state == State.IDLE


def test_ignores_duplicate_print_start(orch):
    job1 = PrintJob(job_id="job1", job_name="benchy")
    job2 = PrintJob(job_id="job2", job_name="cube")
    orch.on_print_event("print_started", job1)
    orch.on_print_event("print_started", job2)
    assert orch.current_job.job_id == "job1"


def test_cancelled_print_still_compiles(orch, config):
    job = PrintJob(job_id="job1", job_name="benchy")
    orch.on_print_event("print_started", job)

    for _ in range(3):
        orch.on_trigger()
        time.sleep(0.3)

    orch.on_print_event("print_cancelled", None)
    time.sleep(2)

    assert orch.state == State.IDLE
    meta_path = Path(config.capture.base_dir) / "job1" / "meta.json"
    meta = json.loads(meta_path.read_text())
    assert meta["cancelled"]


def test_crash_recovery(config):
    job_dir = Path(config.capture.base_dir) / "recovered-job"
    frames_dir = job_dir / "frames"
    frames_dir.mkdir(parents=True)
    for i in range(5):
        (frames_dir / f"frame-{i+1:06d}.jpg").write_bytes(b"\xff\xd8fake")

    meta = {
        "job_id": "recovered-job",
        "job_name": "test",
        "printer_name": "a1",
        "camera": "nikon-d40",
        "started_at": "2026-01-01T00:00:00Z",
        "state": "CAPTURING",
        "frame_count": 5,
        "video_fps": 30,
        "video_compiled": False,
    }
    (job_dir / "meta.json").write_text(json.dumps(meta))

    orch = Orchestrator(
        config=config,
        camera=MockCamera(),
        compiler=MockCompiler(),
        uploader=MockUploader(),
    )
    orch.recover_jobs()
    time.sleep(2)

    assert orch.state == State.IDLE
    updated = json.loads((job_dir / "meta.json").read_text())
    assert updated["upload_status"] == "verified"
