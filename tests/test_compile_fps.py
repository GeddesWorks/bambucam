import pytest

from bambucam.config import CompileConfig


def test_fixed_fps_when_no_target_duration():
    cfg = CompileConfig(fps=6, target_duration_seconds=0)
    assert cfg.fps_for(40) == 6
    assert cfg.fps_for(2000) == 6


def test_target_duration_keeps_short_and_tall_prints_similar_length():
    cfg = CompileConfig(target_duration_seconds=20, min_fps=6, max_fps=60)
    for frames in (200, 600, 1000):
        fps = cfg.fps_for(frames)
        assert 15 <= frames / fps <= 25, f"{frames} frames gave {frames/fps:.1f}s"


def test_a_tall_print_does_not_produce_a_multi_minute_video():
    """900 layers at a fixed 6 fps is 2.5 minutes."""
    cfg = CompileConfig(fps=6, target_duration_seconds=20, min_fps=6, max_fps=60)
    assert 900 / cfg.fps_for(900) < 30


def test_fps_is_clamped_to_max():
    cfg = CompileConfig(target_duration_seconds=1, min_fps=6, max_fps=30)
    assert cfg.fps_for(10_000) == 30


def test_short_print_is_not_slowed_below_min_fps():
    """A 10-frame print at 0.5 fps would be a slideshow."""
    cfg = CompileConfig(target_duration_seconds=20, min_fps=6, max_fps=60)
    assert cfg.fps_for(10) == 6


def test_zero_frames_does_not_divide_by_zero_or_return_zero_fps():
    cfg = CompileConfig(target_duration_seconds=20, min_fps=6)
    assert cfg.fps_for(0) >= 1


@pytest.mark.parametrize("frames", [2, 13, 40, 243, 900, 5000])
def test_fps_is_always_a_usable_positive_int(frames):
    cfg = CompileConfig(target_duration_seconds=20, min_fps=6, max_fps=60)
    fps = cfg.fps_for(frames)
    assert isinstance(fps, int) and fps >= 1
