from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Compiler(ABC):
    @abstractmethod
    def compile(self, frames_dir: Path, output_path: Path,
                fps: int = 30) -> bool:
        """Compile frames into a video. Returns True on success."""
        ...
