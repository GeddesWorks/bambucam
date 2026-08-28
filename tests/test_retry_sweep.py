"""Stranded uploads must retry themselves.

The NAS silently unmounted, a finished 509-frame video failed to upload and
sat in ERROR_UPLOAD until someone noticed a day later and restarted the
daemon. Recovery only ran at startup, so nothing retried on its own.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bambucam.config import BambuCamConfig
from bambucam.orchestrator import Orchestrator
from bambucam.state_machine import State


def _job(base: Path, job_id: str, state: str, frames: int = 3) -> Path:
    d = base / job_id
    (d / "frames").mkdir(parents=True)
    for i in range(1, frames + 1):
        (d / "frames" / f"frame-{i:06d}.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 20)
    (d / "output.mp4").write_bytes(b"video")
    (d / "meta.json").write_text(json.dumps({
        "job_id": job_id, "job_name": job_id, "printer_name": "Jeff",
        "camera": "mock", "started_at": "2026-08-27T20:58:29+00:00",
        "state": state, "frame_count": frames, "video_compiled": True,
    }))
    return d


@pytest.fixture
def orch(tmp_path):
    cfg = BambuCamConfig()
    cfg.capture.base_dir = str(tmp_path / "prints")
    cfg.upload.backend = "none"
    cfg.cleanup.enabled = True
    Path(cfg.capture.base_dir).mkdir(parents=True)

    uploader = MagicMock()
    uploader.upload.return_value = MagicMock(success=True, file_id="/nas/x.mp4",
                                             metadata={})
    uploader.verify.return_value = True
    compiler = MagicMock()
    compiler.compile.return_value = True
    o = Orchestrator(config=cfg, camera=MagicMock(), compiler=compiler,
                     uploader=uploader)
    return o, Path(cfg.capture.base_dir), uploader


def test_error_upload_job_is_retried_and_archived(orch):
    o, base, uploader = orch
    _job(base, "stranded-1787864309", State.ERROR_UPLOAD.value)

    assert o.retry_stranded_jobs() == 1
    uploader.upload.assert_called()
    assert o.state == State.IDLE


def test_sweep_does_nothing_while_a_print_is_capturing(orch):
    """Resuming rebinds the shared _meta/_job_dir; doing that mid-capture
    would corrupt the running print."""
    o, base, uploader = orch
    _job(base, "stranded-1787864309", State.ERROR_UPLOAD.value)
    o._sm.force_state(State.CAPTURING)

    assert o.retry_stranded_jobs() == 0
    uploader.upload.assert_not_called()


def test_healthy_jobs_are_left_alone(orch):
    o, base, uploader = orch
    d = _job(base, "done-1787864309", State.CLEANUP.value)
    meta = json.loads((d / "meta.json").read_text())
    meta["upload_status"] = "verified"
    (d / "meta.json").write_text(json.dumps(meta))

    assert o.retry_stranded_jobs() == 0
    uploader.upload.assert_not_called()


def test_only_error_states_are_swept(orch):
    """A job merely part-way through the pipeline is startup recovery's job,
    not the sweep's — the sweep exists for jobs that already failed."""
    o, base, uploader = orch
    _job(base, "midway-1787864309", State.COMPILING.value)

    assert o.retry_stranded_jobs() == 0


def test_several_stranded_jobs_are_all_retried(orch):
    o, base, _ = orch
    _job(base, "a-1787864301", State.ERROR_UPLOAD.value)
    _job(base, "b-1787864302", State.ERROR_UPLOAD.value)

    assert o.retry_stranded_jobs() == 2
    assert o.state == State.IDLE


def test_sweep_is_configurable_and_disablable():
    cfg = BambuCamConfig()
    assert cfg.upload.retry_sweep_minutes > 0
    cfg.upload.retry_sweep_minutes = 0  # disables the thread
    assert cfg.upload.retry_sweep_minutes == 0
