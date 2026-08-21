import shutil
import subprocess

import pytest

from bambucam.camera.mock import MockCamera


def test_writes_jpeg_with_valid_markers(tmp_path):
    out = MockCamera().capture_and_download(tmp_path / "sub" / "frame-000001.jpg")
    data = out.read_bytes()
    assert data.startswith(b"\xff\xd8\xff")  # SOI + APP0
    assert data.endswith(b"\xff\xd9")        # EOI


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_frame_is_decodable_by_ffmpeg(tmp_path):
    out = MockCamera().capture_and_download(tmp_path / "frame-000001.jpg")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "64,64"
