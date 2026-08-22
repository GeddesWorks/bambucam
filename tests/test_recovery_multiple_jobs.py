"""Recovering more than one unfinished job must not corrupt shared state.

Every job reuses self._meta and self._job_dir. The pipeline runs in a thread,
so starting the next job before the previous finishes lets one job's cleanup
null out the metadata the other is still using — which crashed recovery with
"'NoneType' object has no attribute 'job_id'" and wedged the state machine in
COMPILING, making the daemon refuse the next real print as "not idle".
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bambucam.config import BambuCamConfig
from bambucam.orchestrator import Orchestrator
from bambucam.state_machine import State


def _job(base: Path, job_id: str, state: str, frames: int = 0) -> Path:
    d = base / job_id
    (d / "frames").mkdir(parents=True)
    for i in range(1, frames + 1):
        (d / "frames" / f"frame-{i:06d}.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 20)
    (d / "meta.json").write_text(json.dumps({
        "job_id": job_id, "job_name": job_id, "printer_name": "Jeff",
        "camera": "mock", "started_at": "2026-08-22T00:00:00+00:00",
        "state": state, "frame_count": frames,
    }))
    return d


@pytest.fixture
def orchestrator(tmp_path):
    cfg = BambuCamConfig()
    cfg.capture.base_dir = str(tmp_path / "prints")
    cfg.upload.backend = "none"
    cfg.cleanup.enabled = True
    Path(cfg.capture.base_dir).mkdir(parents=True)

    compiler = MagicMock()
    compiler.compile.return_value = True
    uploader = MagicMock()
    uploader.upload.return_value = MagicMock(success=True, file_id="x", metadata={})
    uploader.verify.return_value = True

    o = Orchestrator(config=cfg, camera=MagicMock(), compiler=compiler,
                     uploader=uploader)
    return o, Path(cfg.capture.base_dir)


def test_two_unfinished_jobs_recover_without_crashing(orchestrator, caplog):
    o, base = orchestrator
    _job(base, "job-a-1787000001", State.CAPTURING.value, frames=3)
    _job(base, "job-b-1787000002", State.UPLOADING.value, frames=3)

    o.recover_jobs()

    assert "NoneType" not in caplog.text
    assert "PIPELINE_ERROR" not in caplog.text


def test_recovery_leaves_the_daemon_idle_and_able_to_accept_a_print(orchestrator):
    """The wedge: state stuck in COMPILING made every later print_started get
    logged as PRINT_IGNORED."""
    o, base = orchestrator
    _job(base, "job-a-1787000001", State.CAPTURING.value, frames=3)
    _job(base, "job-b-1787000002", State.CAPTURING.value, frames=3)

    o.recover_jobs()

    assert o.state == State.IDLE, f"wedged in {o.state}"


def test_recovery_waits_for_each_pipeline_before_starting_the_next(orchestrator):
    o, base = orchestrator
    _job(base, "job-a-1787000001", State.CAPTURING.value, frames=3)
    _job(base, "job-b-1787000002", State.CAPTURING.value, frames=3)

    o.recover_jobs()

    thread = o._pipeline_thread
    assert thread is None or not thread.is_alive(), \
        "recovery returned while a pipeline was still running"
