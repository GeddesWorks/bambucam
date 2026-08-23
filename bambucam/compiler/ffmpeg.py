from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from bambucam.compiler.base import Compiler

logger = logging.getLogger("bambucam")


class FfmpegCompiler(Compiler):
    def __init__(self, codec: str = "libx264", pixel_format: str = "yuv420p",
                 scale_width: int = 1920, preset: str = "veryfast",
                 threads: int = 2, rc_lookahead: int = 10):
        self._codec = codec
        self._pixel_format = pixel_format
        self._scale_width = scale_width
        self._preset = preset
        self._threads = threads
        self._rc_lookahead = rc_lookahead

    def compile(self, frames_dir: Path, output_path: Path,
                fps: int = 30) -> bool:
        frame_count = len(list(frames_dir.glob("frame-*.jpg")))
        if frame_count < 2:
            logger.warning(
                "Only %d frame(s) found, skipping compilation", frame_count,
                extra={"event": "COMPILE_SKIPPED", "frame_count": frame_count},
            )
            return False

        input_pattern = str(frames_dir / "frame-%06d.jpg")
        cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", input_pattern]

        # Scale first: it shrinks every downstream buffer, which is what keeps
        # a long print inside the Pi's memory. -2 keeps the aspect ratio and
        # rounds to an even height, which yuv420p requires.
        if self._scale_width and self._scale_width > 0:
            cmd += ["-vf", f"scale={self._scale_width}:-2"]

        cmd += ["-c:v", self._codec]
        if self._preset:
            cmd += ["-preset", self._preset]
        if self._threads and self._threads > 0:
            cmd += ["-threads", str(self._threads)]
        if self._codec == "libx264" and self._rc_lookahead > 0:
            # x264 holds rc_lookahead raw frames in memory; the default 40 at
            # full resolution is what triggered the OOM kill.
            cmd += ["-x264-params",
                    f"rc-lookahead={self._rc_lookahead}:sync-lookahead=0"]

        cmd += ["-pix_fmt", self._pixel_format,
                "-movflags", "+faststart",
                str(output_path)]

        logger.info(
            "Compiling %d frames at %d FPS", frame_count, fps,
            extra={"event": "COMPILE_STARTED", "frame_count": frame_count},
        )

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3600,
            )
            if result.returncode == 0 and output_path.exists():
                size_mb = output_path.stat().st_size / (1024 * 1024)
                logger.info(
                    "Compilation complete: %.1f MB", size_mb,
                    extra={"event": "COMPILE_COMPLETED"},
                )
                return True
            logger.error(
                "ffmpeg failed: %s", result.stderr[-500:] if result.stderr else "unknown",
                extra={"event": "COMPILE_FAILED"},
            )
            return False
        except subprocess.TimeoutExpired:
            logger.error(
                "ffmpeg timed out after 1 hour",
                extra={"event": "COMPILE_FAILED"},
            )
            return False
        except OSError as e:
            logger.error(
                "ffmpeg not found or not executable: %s", e,
                extra={"event": "COMPILE_FAILED"},
            )
            return False
