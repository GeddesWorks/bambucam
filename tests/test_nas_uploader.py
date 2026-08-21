from datetime import datetime
from pathlib import Path

import pytest

from bambucam.upload.nas import NasUploader


@pytest.fixture
def uploader(tmp_path):
    # mount_check off: tmp_path is not a mount point.
    return NasUploader(base_dir=str(tmp_path / "BambuCam"), mount_check=False)


@pytest.fixture
def video(tmp_path):
    v = tmp_path / "output.mp4"
    v.write_bytes(b"video-bytes" * 100)
    return v


def meta(job_id="benchy-1787328625"):
    return {"job_id": job_id, "job_name": "benchy", "frame_count": 13}


def test_archives_into_year_folder_with_date_prefix(uploader, video):
    result = uploader.upload(video, meta())
    assert result.success
    dest = Path(result.file_id)
    assert dest.exists()
    assert dest.parent.name == str(datetime.fromtimestamp(1787328625).year)
    assert dest.name.endswith("_benchy.mp4")
    assert dest.read_bytes() == video.read_bytes()


def test_filename_uses_print_start_not_upload_time(uploader, video):
    result = uploader.upload(video, meta("thing-1787328625"))
    expected = datetime.fromtimestamp(1787328625).strftime("%Y-%m-%d_%H%M")
    assert Path(result.file_id).name.startswith(expected)


def test_falls_back_to_file_mtime_when_job_id_has_no_timestamp(uploader, video):
    result = uploader.upload(video, meta("no-timestamp-here"))
    assert result.success
    assert Path(result.file_id).name.endswith("_no-timestamp-here.mp4")


def test_second_print_in_same_minute_does_not_overwrite(uploader, video):
    first = uploader.upload(video, meta())
    second = uploader.upload(video, meta())
    assert first.file_id != second.file_id
    assert Path(first.file_id).exists() and Path(second.file_id).exists()


def test_no_part_file_is_left_behind(uploader, video):
    result = uploader.upload(video, meta())
    leftovers = list(Path(result.file_id).parent.glob(".*.part"))
    assert leftovers == []


def test_verify_accepts_a_real_file(uploader, video):
    result = uploader.upload(video, meta())
    assert uploader.verify(result.file_id) is True


def test_verify_rejects_missing_file(uploader, tmp_path):
    assert uploader.verify(str(tmp_path / "nope.mp4")) is False


def test_verify_rejects_empty_file(uploader, tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert uploader.verify(str(empty)) is False


def test_unmounted_share_fails_instead_of_writing_locally(tmp_path, video):
    """The danger: share not mounted looks like a normal empty directory, and
    we quietly fill the Pi's SD card instead of the NAS."""
    up = NasUploader(base_dir=str(tmp_path / "BambuCam"), mount_check=True)
    result = up.upload(video, meta())
    assert result.success is False
    assert result.file_id is None


def test_missing_source_file_is_reported_not_raised(uploader, tmp_path):
    result = uploader.upload(tmp_path / "gone.mp4", meta())
    assert result.success is False
