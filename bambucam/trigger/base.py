from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class TriggerProvider(ABC):
    @abstractmethod
    def start(self, callback: Callable[[], None]) -> None:
        """Begin listening for trigger pulses. Calls callback on each valid pulse."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop listening and release resources."""
        ...
