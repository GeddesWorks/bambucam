from pathlib import Path

from bambucam.models import JobDirectory, JobMeta, PrintJob, UploadResult


def test_print_job_defaults():
    job = PrintJob(job_id="abc", job_name="benchy")
    assert job.started_at is not None
    assert job.printer_name == ""


def test_job_meta_from_print_job():
    job = PrintJob(job_id="abc", job_name="benchy", printer_name="a1")
    meta = JobMeta.from_print_job(job)
    assert meta.job_id == "abc"
    assert meta.state == "PRINT_STARTING"
    assert meta.frame_count == 0
    assert meta.video_fps == 30


def test_job_meta_round_trip():
    job = PrintJob(job_id="abc", job_name="benchy")
    meta = JobMeta.from_print_job(job)
    meta.frame_count = 42
    data = meta.to_dict()
    restored = JobMeta.from_dict(data)
    assert restored.job_id == "abc"
    assert restored.frame_count == 42


def test_job_directory_create(tmp_path):
    job_dir = JobDirectory.create(tmp_path, "test-job")
    assert job_dir.frames_dir.exists()
    assert job_dir.root == tmp_path / "test-job"


def test_job_directory_frame_path(tmp_path):
    job_dir = JobDirectory.create(tmp_path, "test-job")
    assert job_dir.next_frame_path(1).name == "frame-000001.jpg"
    assert job_dir.next_frame_path(999).name == "frame-000999.jpg"


def test_job_directory_frame_count(tmp_path):
    job_dir = JobDirectory.create(tmp_path, "test-job")
    assert job_dir.frame_count() == 0
    (job_dir.frames_dir / "frame-000001.jpg").write_bytes(b"fake")
    (job_dir.frames_dir / "frame-000002.jpg").write_bytes(b"fake")
    assert job_dir.frame_count() == 2


def test_upload_result():
    result = UploadResult(success=True, file_id="abc123")
    assert result.success
    assert result.file_id == "abc123"
    assert not result.verified
