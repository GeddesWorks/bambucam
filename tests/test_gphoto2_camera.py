import pytest

from bambucam.camera.gphoto2 import GPhoto2Camera
from bambucam.camera.mock import _MOCK_JPEG


def test_accepts_real_jpeg(tmp_path):
    frame = tmp_path / "frame-000001.jpg"
    frame.write_bytes(_MOCK_JPEG)
    GPhoto2Camera._assert_jpeg(frame)  # does not raise
    assert frame.exists()


def test_rejects_raw_named_jpg(tmp_path):
    """A camera set to NEF writes RAW bytes to whatever filename we asked for."""
    frame = tmp_path / "frame-000001.jpg"
    frame.write_bytes(b"MM\x00*\x00\x00\x00\x08nikon-nef-payload")
    with pytest.raises(RuntimeError, match="non-JPEG"):
        GPhoto2Camera._assert_jpeg(frame)
    assert not frame.exists(), "unusable frame should not be left behind"


def test_rejects_empty_file(tmp_path):
    frame = tmp_path / "frame-000001.jpg"
    frame.write_bytes(b"")
    with pytest.raises(RuntimeError, match="non-JPEG"):
        GPhoto2Camera._assert_jpeg(frame)
