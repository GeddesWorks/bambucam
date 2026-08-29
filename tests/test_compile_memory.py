"""Encoding must stay inside the Pi's memory.

The Pi 3B has 905MB and no swap. x264 buffers rc_lookahead raw frames, and a
3008x2000 frame is ~9MB, so a full-resolution encode of a long print reached
2.2GB virtual and was OOM-killed after 57 seconds — with 401 good frames on
disk and nothing to show for them.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

from bambucam.compiler.ffmpeg import FfmpegCompiler
from bambucam.config import CompileConfig


def _command_for(tmp_path, **kwargs):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(1, 4):
        (frames / f"frame-{i:06d}.jpg").write_bytes(b"\xff\xd8\xff")
    c = FfmpegCompiler(**kwargs)
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        c.compile(frames, tmp_path / "out.mp4", fps=20)
    return run.call_args[0][0]


def test_defaults_scale_down_and_cap_lookahead(tmp_path):
    cmd = _command_for(tmp_path)
    assert "-vf" in cmd and "scale=1920:-2" in cmd[cmd.index("-vf") + 1]
    params = cmd[cmd.index("-x264-params") + 1]
    assert "rc-lookahead=10" in params
    assert "sync-lookahead=0" in params
    assert cmd[cmd.index("-threads") + 1] == "2"


def test_scaling_can_be_disabled_for_native_resolution(tmp_path):
    cmd = _command_for(tmp_path, scale_width=0)
    assert "-vf" not in cmd


def test_x264_params_are_not_passed_to_other_codecs(tmp_path):
    """-x264-params is libx264-only; ffmpeg errors out on it otherwise."""
    cmd = _command_for(tmp_path, codec="libx265")
    assert "-x264-params" not in cmd


def test_scale_keeps_even_height_for_yuv420p(tmp_path):
    """yuv420p requires even dimensions; -1 can produce an odd height."""
    cmd = _command_for(tmp_path, scale_width=1280)
    assert "scale=1280:-2" in cmd[cmd.index("-vf") + 1]


def test_config_defaults_are_memory_safe():
    cfg = CompileConfig()
    assert 0 < cfg.scale_width <= 1920
    assert cfg.rc_lookahead <= 20
    assert cfg.threads <= 4


def test_output_still_ends_with_the_destination_path(tmp_path):
    cmd = _command_for(tmp_path)
    assert cmd[-1].endswith("out.mp4")
    assert "+faststart" in cmd


def test_quality_defaults_are_not_the_memory_panic_settings(tmp_path):
    """veryfast + ffmpeg's default crf 23 decoded to 1.71 edge energy against
    a 2.40 ceiling for the same downscale — about a third of the detail thrown
    away. The memory ceiling was rc_lookahead, never the preset, so quality was
    given up for nothing."""
    cmd = _command_for(tmp_path)
    assert cmd[cmd.index("-preset") + 1] == "medium"
    assert int(cmd[cmd.index("-crf") + 1]) <= 20


def test_downscale_uses_lanczos(tmp_path):
    """A downscale is where most of the frame's detail is decided; the default
    bicubic is visibly softer."""
    cmd = _command_for(tmp_path)
    assert "flags=lanczos" in cmd[cmd.index("-vf") + 1]


def test_crf_can_be_disabled_for_codecs_that_do_not_take_it(tmp_path):
    cmd = _command_for(tmp_path, crf=0)
    assert "-crf" not in cmd


def test_lookahead_is_still_capped_for_memory(tmp_path):
    """Quality went up; the OOM guard must not have been traded away for it."""
    cmd = _command_for(tmp_path)
    assert "rc-lookahead=10" in cmd[cmd.index("-x264-params") + 1]
